# walboard — tiny CLI for your Plane kanban board
#
# Build:  docker build -t wallydk24/walboard .
# Run:    docker run --rm -e PLANE_API_KEY=$KEY \
#           -e WALBOARD_WORKSPACE=<workspace-slug> \
#           -e WALBOARD_PROJECT=<project-uuid> \
#           wallydk24/walboard list
#
# Your Plane API key is NEVER baked into the image — pass it at runtime
# via PLANE_API_KEY. Stdlib only — no dependencies.

FROM python:3.12-alpine

WORKDIR /app
COPY walboard.py ./
RUN adduser -D wb && chown -R wb:wb /app
USER wb

ENTRYPOINT ["python3", "/app/walboard.py"]
CMD ["--help"]
