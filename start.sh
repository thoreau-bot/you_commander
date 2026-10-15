#!/usr/bin/env sh
# macOS / Linux: start YouCommander on http://127.0.0.1:8765
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { echo "Run ./install.sh first."; exit 1; }
export ORG_DB="${ORG_DB:-organizer.db}"
( sleep 1.5; (xdg-open http://127.0.0.1:8765 || open http://127.0.0.1:8765) >/dev/null 2>&1 ) &
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765
