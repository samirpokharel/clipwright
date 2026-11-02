#!/usr/bin/env bash
# Runs the container tests inside the supoclip-backend image (needs the cached job jNQXAC9IVRw).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
exec docker run --rm \
  -e TRANSCRIPTION_PROVIDER=whisper -e TEMP_DIR=/work/tmp -e XDG_CACHE_HOME=/work/cache -e HOME=/work/cache \
  -e PYTHONPATH=/work:/app \
  -v "$ROOT":/work -w /app \
  supoclip-backend:latest .venv/bin/python -m unittest discover -s /work/tests/container -t /work -v
