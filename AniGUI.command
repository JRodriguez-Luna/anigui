#!/bin/bash
# Double-click to run AniGUI from source (no build step). First run sets up .venv.
# App output goes to anigui.log next to this file.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -x .venv/bin/python ]; then
  echo "Setting up AniGUI (first run, about a minute)…"
  python3 -m venv .venv || { echo "Could not create .venv"; read -r; exit 1; }
fi
if ! .venv/bin/python -c "import PySide6, certifi" 2>/dev/null || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "pip install failed"; read -r; exit 1; }
  touch .venv/.installed
fi

echo "Starting AniGUI… (you can close this window once the app opens)"
.venv/bin/python main.py >anigui.log 2>&1 &
disown
exit 0
