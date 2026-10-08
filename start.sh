#!/usr/bin/env bash
# Start the Market Ecology Simulator. Sets up the environment on first run.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Setting up the virtual environment..."
  python3 -m venv .venv
  "$PY" -m pip install --quiet --upgrade pip
fi

# Cheap check: if numpy is missing the environment was never fully installed.
if ! "$PY" -c "import numpy, scipy, fastapi, uvicorn" 2>/dev/null; then
  echo "Installing dependencies..."
  "$PY" -m pip install --quiet -r requirements.txt
fi

echo
echo "Warming up the market: 110 trading days, about 20 seconds."
echo "The validation panel needs 100 days before it can say anything."
echo
echo "  http://127.0.0.1:${PORT}"
echo

# Open the browser once the server answers, without blocking the server itself.
(
  for _ in $(seq 1 90); do
    if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/state"; then
      command -v open >/dev/null && open "http://127.0.0.1:${PORT}" || true
      break
    fi
    sleep 1
  done
) &

exec "$PY" -m uvicorn mes.api:app --host 127.0.0.1 --port "${PORT}"
