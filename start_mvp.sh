#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "Starting MTG Price Tracker on http://${HOST}:${PORT}"
echo "Local link: http://localhost:${PORT}"
echo "Stop with Ctrl+C."

exec python3 run_mvp.py --host "${HOST}" --port "${PORT}"
