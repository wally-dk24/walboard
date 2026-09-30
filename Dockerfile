# walboard — tiny CLI for your Plane kanban board
# (multi-arch: linux/amd64, linux/arm64 — e.g. Raspberry Pi)
#
# Build:  podman build --platform linux/arm64 -t wallydk24/walboard:arm64 .
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
USER 1000

ENTRYPOINT ["python3", "/app/walboard.py"]
CMD ["--help"]
