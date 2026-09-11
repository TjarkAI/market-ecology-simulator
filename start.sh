#!/usr/bin/env bash
# Start the Market Ecology Simulator. Sets up the environment on first run.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Richte virtuelle Umgebung ein..."
  python3 -m venv .venv
  "$PY" -m pip install --quiet --upgrade pip
fi

# Cheap check: if numpy is missing the environment was never fully installed.
if ! "$PY" -c "import numpy, scipy, fastapi, uvicorn" 2>/dev/null; then
  echo "Installiere Abhängigkeiten..."
  "$PY" -m pip install --quiet -r requirements.txt
fi

echo
echo "Der Markt wird aufgewärmt — 110 Handelstage, etwa 20 Sekunden."
echo "Das Validierungspanel braucht 100 Tage, um etwas aussagen zu können."
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
