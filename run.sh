#!/usr/bin/env bash
# SupportSphere AI - one-command start for macOS / Linux:   ./run.sh
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.9+ from https://www.python.org/downloads/ and run again."
  exit 1
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment (first run only)..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install -q -r requirements.txt

PORT_TO_USE="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2)"
PORT_TO_USE="${PORT:-${PORT_TO_USE:-5000}}"
echo
echo "  Starting SupportSphere AI at http://127.0.0.1:${PORT_TO_USE}"
echo "  Press Ctrl+C to stop."
echo
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:${PORT_TO_USE}") || (command -v open >/dev/null && open "http://127.0.0.1:${PORT_TO_USE}") || true ) >/dev/null 2>&1 &
python app.py
