#!/usr/bin/env sh
# macOS / Linux: create the environment and install the (small) requirements.
cd "$(dirname "$0")" || exit 1
python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt && echo "Install finished. Now run ./start.sh"
