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
import subprocess
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
    # Transport via curl, not urllib: Python's http.client cannot complete
    # large chunked reads from api.plane.so through the egress proxy
    # (persistent http.client.IncompleteRead, observed 2026-10-06), while
    # curl handles the same responses fine. Same fix as plane_pages.py.
    url = cfg["base"] + path
    cmd = ["curl", "-s", "-m", "120", "-X", method,
           "-H", "x-api-key: " + cfg["key"],
           "-H", "Content-Type: application/json",
           "-H", "User-Agent: walboard/0.1",
           "-w", "\n%{http_code}", url]
    if data is not None:
        cmd += ["-d", json.dumps(data)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=130).stdout
    body_raw, _, code = out.rpartition("\n")
    try:
        code = int(code.strip())
    except ValueError:
        die(f"Plane API {method} {path} -> curl transport error: {out[-200:]}")
    if code >= 400:
        die(f"Plane API {method} {path} -> HTTP {code}: {body_raw[:200]}")
    return json.loads(body_raw) if body_raw.strip() else {}


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


def fetch_issues(cfg: dict) -> list:
    """Return the project's issues (up to 100)."""
    res = req(cfg, "GET", "/issues/?per_page=100")
    items = res.get("results", res if isinstance(res, list) else [])
    return sorted(items, key=lambda it: it.get("sequence_id", 0))


def fetch_states(cfg: dict) -> tuple:
    """Return (states: friendly-name -> id, names: id -> friendly-name)."""
    states = state_ids(cfg)
    return states, {v: k for k, v in states.items()}


def cmd_list(cfg: dict, args: argparse.Namespace) -> None:
    items = fetch_issues(cfg)
    states, names = fetch_states(cfg)
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

    sv = sub.add_parser("serve", help="Run the branded kanban board web UI.")
    sv.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0).")
    sv.add_argument("--port", type=int, default=8080, help="Port (default 8080).")
    sv.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if args.cmd == "serve":
        cmd_serve(args)
        return
    cfg = config()
    args.func(cfg, args)


# ---------------------------------------------------------------- serve mode
#
#   walboard serve [--port 8080]
#
# A branded kanban board web UI over the Plane project: three columns
# (backlog / in-progress / done), card detail pages, and add/move/edit
# forms. Plane credentials stay server-side (PLANE_API_KEY /
# ~/.config/walboard/api_key + WALBOARD_WORKSPACE / WALBOARD_PROJECT) —
# the browser never sees them.
#
#   GET  /              board
#   GET  /card?id=...   card detail
#   POST /add           add a card
#   POST /move          move a card
#   POST /edit          edit a card
#   GET  /healthz       "ok"

WL_STYLE = """<style>
.wl-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.wl-col{background:#221c15;border:1px solid #332b21;border-radius:14px;padding:12px}
.wl-col h3{margin:.2em .2em .8em;font-size:15px;color:#f3e6cf;
  display:flex;align-items:center;gap:8px}
.wl-card{display:block;background:#2b2318;border:1px solid #3d3222;border-radius:10px;
  padding:10px 12px;margin-bottom:10px;text-decoration:none;color:inherit}
.wl-card:hover{border-color:#7a5a2e}
.wl-card .wl-seq{font-size:12px;color:#a49176}
.wl-card .wl-title{font-weight:600;color:#f3e6cf;margin:.15em 0 .3em;line-height:1.4}
.wl-labels{display:flex;gap:6px;flex-wrap:wrap}
.wl-empty{color:#a49176;font-size:13px;font-style:italic;padding:4px 2px 10px}
.wl-desc{color:#cbbfa8;line-height:1.6;white-space:pre-wrap;margin:1em 0}
.wl-back{display:inline-block;margin-bottom:.6em;color:#e8a33d;font-size:14px;
  text-decoration:none}
.wl-add-grid{display:grid;grid-template-columns:2fr 2fr 1fr 1fr;gap:10px}
@media (max-width:640px){.wl-add-grid{grid-template-columns:1fr}}
</style>"""

COLUMNS = ("backlog", "in-progress", "done")


def _esc(s):
    return ("" if s is None else str(s)).replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _desc_text(issue):
    import re
    import html as _h
    raw = issue.get("description_html") or ""
    text = _h.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()


def _label_badges(issue):
    out = []
    for l in issue.get("labels_list", []) or []:
        out.append('<span class="wb-badge">%s</span>' % _esc(l.get("name", "")))
    return " ".join(out)


def _board_html(cfg, states, names):
    try:
        issues = fetch_issues(cfg)
    except SystemExit:
        return ('<div class="wb-card"><span class="wb-badge b-red">error</span>'
                "<p>Could not reach the Plane API — check the server log.</p></div>")
    cols = []
    for col in COLUMNS:
        sid = states.get(col)
        cards = []
        for it in issues:
            if it.get("state") != sid:
                continue
            cards.append(
                '<a class="wl-card" href="/card?id=%s">'
                '<div class="wl-seq">#%s · %s</div>'
                '<div class="wl-title">%s</div>'
                '<div class="wl-labels">%s</div></a>'
                % (_esc(it["id"]), _esc(it.get("sequence_id", "?")),
                   _esc(short_id(it["id"])), _esc(it.get("name", "")),
                   _label_badges(it)))
        cols.append(
            '<div class="wl-col"><h3>%s <span class="wb-badge">%d</span></h3>%s</div>'
            % (_esc(col), len(cards),
               "".join(cards) or '<div class="wl-empty">no cards</div>'))
    add_form = """
<div class="wb-card">
  <h2>Add a card</h2>
  <form action="/add" method="post">
    <div class="wl-add-grid">
      <div class="wb-field"><label for="a-title">Title</label>
        <input class="wb-input" id="a-title" name="title" required maxlength="200"></div>
      <div class="wb-field"><label for="a-desc">Description</label>
        <input class="wb-input" id="a-desc" name="desc"></div>
      <div class="wb-field"><label for="a-label">Label</label>
        <select class="wb-select" id="a-label" name="label">
          <option value="task">task</option><option value="bug">bug</option>
          <option value="idea">idea</option></select></div>
      <div class="wb-field"><label for="a-state">Column</label>
        <select class="wb-select" id="a-state" name="state">
          <option value="backlog">backlog</option>
          <option value="in-progress">in-progress</option></select></div>
    </div>
    <div class="wb-btn-row">
      <button class="wb-btn wb-btn-primary" type="submit">Add card</button>
    </div>
  </form>
</div>"""
    return add_form + '<div class="wl-cols">%s</div>' % "".join(cols)


def _card_html(cfg, states, issue_id):
    try:
        issue = req(cfg, "GET", f"/issues/{issue_id}/")
    except SystemExit:
        return ('<div class="wb-card"><a class="wl-back" href="/">← board</a>'
                '<span class="wb-badge b-red">error</span>'
                "<p>Card not found.</p></div>")
    names = {v: k for k, v in states.items()}
    state_name = names.get(issue.get("state"), issue.get("state_name", ""))
    opts = "".join(
        '<option value="%s"%s>%s</option>' % (s, " selected" if s == state_name else "", s)
        for s in ("backlog", "in-progress", "done", "cancelled"))
    return """
<div class="wb-card">
  <a class="wl-back" href="/">← board</a>
  <h2>#%(seq)s — %(name)s</h2>
  <p><span class="wb-badge">%(state)s</span> %(labels)s</p>
  %(desc)s
</div>
<div class="wb-card">
  <h2>Move</h2>
  <form action="/move" method="post">
    <input type="hidden" name="id" value="%(id)s">
    <div class="wb-field"><label for="m-state">Move to</label>
      <select class="wb-select" id="m-state" name="state">%(opts)s</select></div>
    <div class="wb-btn-row">
      <button class="wb-btn wb-btn-primary" type="submit">Move card</button>
    </div>
  </form>
</div>
<div class="wb-card">
  <h2>Edit</h2>
  <form action="/edit" method="post">
    <input type="hidden" name="id" value="%(id)s">
    <div class="wb-field"><label for="e-title">Title</label>
      <input class="wb-input" id="e-title" name="title" value="%(name_attr)s"></div>
    <div class="wb-field"><label for="e-desc">Description</label>
      <textarea class="wb-input" id="e-desc" name="desc" rows="4">%(desc_attr)s</textarea></div>
    <div class="wb-btn-row">
      <button class="wb-btn wb-btn-primary" type="submit">Save changes</button>
    </div>
  </form>
</div>
""" % {"seq": _esc(issue.get("sequence_id", "?")), "id": _esc(issue.get("id", "")),
       "name": _esc(issue.get("name", "")), "name_attr": _esc(issue.get("name", "")),
       "state": _esc(state_name), "labels": _label_badges(issue),
       "desc": ('<div class="wl-desc">%s</div>' % _esc(_desc_text(issue))
                if _desc_text(issue) else ""),
       "desc_attr": _esc(_desc_text(issue)), "opts": opts}


def cmd_serve(args: argparse.Namespace) -> None:
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from brand.page import render, brand_asset

    try:
        cfg = config()
        states, _ = fetch_states(cfg)
    except SystemExit:
        cfg, states = None, {}

    def shell(title, content):
        return render("walboard", "Your Plane kanban board", title, content,
                      footer_extra="walboard")

    def need_cfg(handler):
        if cfg is None:
            handler._send(shell(
                "Walboard",
                '<div class="wb-card"><span class="wb-badge b-red">not configured'
                '</span><p class="wb-sub">This server needs '
                '<span class="rc-hash">WALBOARD_WORKSPACE</span>, '
                '<span class="rc-hash">WALBOARD_PROJECT</span> and a Plane API key '
                '(<span class="rc-hash">PLANE_API_KEY</span> or '
                '<span class="rc-hash">~/.config/walboard/api_key</span>).'
                "</p></div>"), code=500)
            return False
        return True

    class BoardHandler(BaseHTTPRequestHandler):
        server_version = "walboard/serve"

        def log_message(self, fmt, *a):
            sys.stderr.write("walboard: %s\n" % (fmt % a))

        def _send(self, body, ctype="text/html; charset=utf-8", code=200):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self):
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def _form(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 1024 * 1024:
                return None
            return parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

        def do_GET(self):
            parsed = urlparse(self.path)
            asset = brand_asset(parsed.path)
            if asset:
                ctype, data = asset
                return self._send(data, ctype)
            if parsed.path == "/healthz":
                return self._send("ok", "text/plain; charset=utf-8")
            if not need_cfg(self):
                return
            if parsed.path in ("/", "/index.html"):
                return self._send(WL_STYLE + shell(
                    "Walboard", _board_html(cfg, states, {v: k for k, v in states.items()})))
            if parsed.path == "/card":
                issue_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
                if not issue_id:
                    self.send_error(400, "missing id")
                    return
                return self._send(WL_STYLE + shell(
                    "Walboard", _card_html(cfg, states, issue_id)))
            self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/add", "/move", "/edit"):
                self.send_error(404)
                return
            if not need_cfg(self):
                return
            form = self._form()
            if form is None:
                self.send_error(400, "bad form")
                return
            get = lambda k: (form.get(k, [""])[0] or "").strip()
            try:
                if path == "/add":
                    title = get("title")
                    if not title:
                        self.send_error(400, "missing title")
                        return
                    label = get("label") or "task"
                    if label not in ("task", "bug", "idea"):
                        label = "task"
                    state = get("state") or "backlog"
                    if state not in ("backlog", "in-progress"):
                        state = "backlog"
                    payload = {"name": title, "state": states[state]}
                    if get("desc"):
                        payload["description_html"] = "<p>" + _esc(get("desc")) + "</p>"
                    try:
                        payload["labels"] = [label_id(cfg, label)]
                    except SystemExit:
                        pass  # label missing on project — create the card anyway
                    req(cfg, "POST", "/issues/", payload)
                elif path == "/move":
                    issue_id, state = get("id"), get("state")
                    if not issue_id or state not in states:
                        self.send_error(400, "bad move")
                        return
                    req(cfg, "PATCH", f"/issues/{issue_id}/", {"state": states[state]})
                else:  # /edit
                    issue_id = get("id")
                    if not issue_id:
                        self.send_error(400, "missing id")
                        return
                    payload = {}
                    if get("title"):
                        payload["name"] = get("title")
                    payload["description_html"] = (
                        "<p>" + _esc(get("desc")).replace("\n", "<br/>") + "</p>"
                        if get("desc") else "")
                    if not payload.get("name") and not get("desc"):
                        self.send_error(400, "nothing to change")
                        return
                    req(cfg, "PATCH", f"/issues/{issue_id}/", payload)
            except SystemExit:
                self.send_error(502, "Plane API error — check the server log")
                return
            self._redirect()

    httpd = ThreadingHTTPServer((args.host, args.port), BoardHandler)
    httpd.daemon_threads = True
    host = "localhost" if args.host == "0.0.0.0" else args.host
    print("walboard: serving the board UI at http://%s:%d/" % (host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
