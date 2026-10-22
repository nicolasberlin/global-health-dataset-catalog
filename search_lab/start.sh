#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -f search_lab/.env ]; then
  set -a
  . ./search_lab/.env
  set +a
fi
export API_AUTH_MODE="${API_AUTH_MODE:-local}"
if [ "$API_AUTH_MODE" != local ]; then
  echo "The laboratory requires API_AUTH_MODE=local." >&2
  exit 1
fi
export PYTHONPATH="backend:.${PYTHONPATH:+:$PYTHONPATH}"
python_bin="$PWD/.venv/bin/python"
if [ ! -x "$python_bin" ]; then
  echo 'Install project development dependencies in .venv first.' >&2
  exit 1
fi
"$python_bin" -m uvicorn search_lab.backend.app:app --host 127.0.0.1 --port 8003 --no-proxy-headers &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix search_lab/frontend run dev
