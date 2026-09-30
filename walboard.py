#!/usr/bin/env python3
"""
walboard — a tiny CLI for your Plane kanban board.

Setup:
    export PLANE_API_KEY="$(cat /path/to/plane/api_key)"   # or store in ~/.config/walboard/api_key
    export WALBOARD_WORKSPACE="your-workspace-slug"
    export WALBOARD_PROJECT="your-project-id"

Usage:
    walboard list [--state backlog|in-progress|done|cancelled]
    walboard show <issue-id>
    walboard add "Card title" [--desc "..."] [--label task|bug|idea] [--state backlog|in-progress]
    walboard move <issue-id> backlog|in-progress|done|cancelled
    walboard edit <issue-id> [--title "..."] [--desc "..."]

Everything uses the Python standard library — no dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

DEFAULT_STATES = {"backlog": None, "in-progress": None, "done": None}


def die(msg: str) -> "typing.NoReturn":  # noqa: F821  (typed lazily below)
    print(f"walboard: error: {msg}", file=sys.stderr)
    sys.exit(1)


def load_key() -> str:
    key = os.environ.get("PLANE_API_KEY")
    if key:
        return key.strip()
    path = os.path.expanduser("~/.config/walboard/api_key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    die("no API key: set PLANE_API_KEY or put it in ~/.config/walboard/api_key")


def config() -> dict:
    ws = os.environ.get("WALBOARD_WORKSPACE")
    proj = os.environ.get("WALBOARD_PROJECT")
    if not ws or not proj:
        die("set WALBOARD_WORKSPACE and WALBOARD_PROJECT environment variables")
    return {
        "workspace": ws,
        "project": proj,
        "key": load_key(),
        "base": f"https://api.plane.so/api/v1/workspaces/{ws}/projects/{proj}",
    }


def req(cfg: dict, method: str, path: str, data: dict | None = None) -> dict:
    headers = {
        "x-api-key": cfg["key"],
        "Content-Type": "application/json",
        "User-Agent": "walboard/0.1",
    }
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(cfg["base"] + path, data=body,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()
        except Exception:
            detail = ""
        die(f"Plane API {method} {path} -> HTTP {e.code}: {detail[:200]}")


def state_ids(cfg: dict) -> dict:
    """Map friendly state names -> Plane state ids."""
    res = req(cfg, "GET", "/states/")
    out = {}
    for s in res.get("results", res if isinstance(res, list) else []):
        name = (s.get("name") or "").strip().lower()
        if "cancel" in name:
            out["cancelled"] = s["id"]
        elif "backlog" in name or "to do" in name:
            out["backlog"] = s["id"]
        elif "progress" in name:
            out["in-progress"] = s["id"]
        elif "done" in name or "complete" in name:
            out["done"] = s["id"]
    if not all(out.get(k) for k in ("backlog", "in-progress", "done", "cancelled")):
        die("could not resolve backlog/in-progress/done/cancelled state ids on this project")
    return out


def label_id(cfg: dict, name: str) -> str:
    res = req(cfg, "GET", "/labels/")
    for lbl in res.get("results", res if isinstance(res, list) else []):
        if (lbl.get("name") or "").lower() == name.lower():
            return lbl["id"]
    die(f"no label named '{name}' on this project")


def short_id(full: str) -> str:
    return full[:8]


def cmd_list(cfg: dict, args: argparse.Namespace) -> None:
    res = req(cfg, "GET", "/issues/?per_page=100")
    items = res.get("results", res if isinstance(res, list) else [])
    states = state_ids(cfg)
    names = {v: k for k, v in states.items()}
    wanted = states.get(args.state) if args.state else None
    rows = []
    for it in items:
        if wanted and it.get("state") != wanted:
            continue
        seq = it.get("sequence_id", "?")
        rows.append((seq, short_id(it["id"]), it.get("name", ""),
                     names.get(it.get("state"), it.get("state_name", ""))))
    if not rows:
        print("(no cards)")
        return
    rows.sort(key=lambda r: r[0])
    for seq, sid, name, state_name in rows:
        print(f"{seq:>4}  {sid}  [{state_name}]  {name}")


def resolve_issue(cfg: dict, prefix: str) -> str:
    res = req(cfg, "GET", "/issues/?per_page=100")
    items = res.get("results", res if isinstance(res, list) else [])
    matches = [it["id"] for it in items if it["id"].startswith(prefix.lower())]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        die(f"no card starts with '{prefix}'")
    die(f"'{prefix}' is ambiguous: " + ", ".join(short_id(m) for m in matches))


def cmd_show(cfg: dict, args: argparse.Namespace) -> None:
    issue_id = resolve_issue(cfg, args.issue)
    issue = req(cfg, "GET", f"/issues/{issue_id}/")
    print(f"Title : {issue.get('name')}")
    print(f"State : {issue.get('state_name', issue.get('state'))}")
    print(f"Labels: {', '.join(l.get('name','') for l in issue.get('labels_list', [])) or '-'}")
    import re, html as _h
    raw = issue.get("description_html") or ""
    text = _h.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        print("Desc  : " + text[:2000])


def cmd_add(cfg: dict, args: argparse.Namespace) -> None:
    states = state_ids(cfg)
    payload: dict = {"name": args.title, "state": states[args.state]}
    if args.desc:
        payload["description_html"] = "<p>" + args.desc.replace("\n", "<br/>") + "</p>"
    if args.label:
        payload["labels"] = [label_id(cfg, args.label)]
    issue = req(cfg, "POST", "/issues/", payload)
    print(f"created #{issue.get('sequence_id', '?')}  {issue['id']}")
    print(f"  {issue.get('name')}")


def cmd_move(cfg: dict, args: argparse.Namespace) -> None:
    states = state_ids(cfg)
    issue_id = resolve_issue(cfg, args.issue)
    req(cfg, "PATCH", f"/issues/{issue_id}/", {"state": states[args.state]})
    print(f"moved {short_id(issue_id)} -> {args.state}")


def cmd_edit(cfg: dict, args: argparse.Namespace) -> None:
    issue_id = resolve_issue(cfg, args.issue)
    payload: dict = {}
    if args.title:
        payload["name"] = args.title
    if args.desc is not None:
        payload["description_html"] = (
            "<p>" + args.desc.replace("\\n", "<br/>") + "</p>" if args.desc else "")
    if not payload:
        die("nothing to change: pass --title and/or --desc")
    req(cfg, "PATCH", f"/issues/{issue_id}/", payload)
    print(f"edited {short_id(issue_id)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="walboard",
                                     description="Tiny CLI for your Plane kanban board.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="List cards.")
    p.add_argument("--state", choices=["backlog", "in-progress", "done", "cancelled"])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="Show one card in detail.")
    p.add_argument("issue", help="Issue id (or its 8-char prefix).")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("add", help="Add a card.")
    p.add_argument("title")
    p.add_argument("--desc", default="")
    p.add_argument("--label", choices=["task", "bug", "idea"], default="task")
    p.add_argument("--state", choices=["backlog", "in-progress"], default="backlog")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("move", help="Move a card between states.")
    p.add_argument("issue", help="Issue id (or its 8-char prefix).")
    p.add_argument("state", choices=["backlog", "in-progress", "done", "cancelled"])
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("edit", help="Edit a card's title and/or description.")
    p.add_argument("issue", help="Issue id (or its 8-char prefix).")
    p.add_argument("--title", default="")
    p.add_argument("--desc", default=None)
    p.set_defaults(func=cmd_edit)

    args = parser.parse_args()
    cfg = config()
    args.func(cfg, args)


if __name__ == "__main__":
    main()
