#!/usr/bin/env bash
# Start Hearth on macOS or Linux:   ./start.sh      (needs Python 3.10 or newer)
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer from https://www.python.org/downloads/ and try again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Setting up for the first time. This takes about a minute..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

# open the browser a moment after the server starts (ignore if there is no browser command)
( sleep 3; (open http://127.0.0.1:8765/ || xdg-open http://127.0.0.1:8765/) >/dev/null 2>&1 || true ) &
exec python -m hearth.server
