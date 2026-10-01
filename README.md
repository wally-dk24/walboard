# walboard

A tiny CLI for your [Plane](https://plane.so) kanban board. Stdlib only — no dependencies.

I run a personal kanban board (WAL) where I log tasks, ideas, and bugs, and I got tired of
opening the web UI for every small move. So this exists.

## Setup

```bash
# one of these:
export PLANE_API_KEY="plane_api_..."            # or put the key in ~/.config/walboard/api_key

# always:
export WALBOARD_WORKSPACE="your-workspace-slug"
export WALBOARD_PROJECT="your-project-uuid"
```

Get a Plane API key from **Settings → API tokens** in your Plane workspace.

## Usage

```bash
./walboard.py list                       # all cards
./walboard.py list --state in-progress   # one column
./walboard.py show 6da48801              # card detail
./walboard.py add "Water the plants" --label task
./walboard.py add "Refactor auth" --label bug --state in-progress --desc "details here"
./walboard.py move 6da48801 done         # full or partial issue id both work
```

State names map automatically to your project's Backlog / In Progress / Done columns,
so it survives custom state naming.

## License

MIT

## Docker

```bash
docker pull wallydk24/walboard
docker run --rm -e PLANE_API_KEY=$KEY \
  -e WALBOARD_WORKSPACE=<workspace-slug> -e WALBOARD_PROJECT=<project-uuid> \
  wallydk24/walboard list
```

## Web UI

`walboard serve` runs a small kanban board UI in the shared wally-brand
skin: backlog / in-progress / done columns, card detail pages, and
add/move/edit forms. Credentials stay server-side — the browser never sees
your Plane API key.

```bash
docker run -p 8080:8080 -e PLANE_API_KEY=$KEY \
  -e WALBOARD_WORKSPACE=<workspace-slug> -e WALBOARD_PROJECT=<project-uuid> \
  wallydk24/walboard serve
# or locally:
python3 walboard.py serve --port 8080
```

Then open http://localhost:8080/. `GET /healthz` returns `ok`.
