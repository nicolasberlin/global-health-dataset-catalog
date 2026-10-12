#!/bin/sh
set -eu
python3 /app/browser/public_proxy.py &
proxy_pid=$!
trap 'kill "$proxy_pid" 2>/dev/null || true' EXIT
node /app/browser/service.cjs
