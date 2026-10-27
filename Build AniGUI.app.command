#!/bin/bash
# Double-click to build AniGUI.app and install it in ~/Applications.
# Re-run after code updates to rebuild. A log is saved to build/build.log.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p build
LOG="build/build.log"
fail() { echo; echo "Build failed: $1"; echo "Details: $(pwd)/$LOG"; echo "Press Return to close."; read -r; exit 1; }

{
  echo "=== AniGUI build — $(date)"
  echo "python: $(command -v python3) ($(python3 --version 2>&1)), arch $(uname -m)"
} >"$LOG"

echo "▸ Preparing Python environment…"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv >>"$LOG" 2>&1 || fail "could not create .venv"
fi
.venv/bin/python -m pip install -q --upgrade pip >>"$LOG" 2>&1
.venv/bin/python -m pip install -q -r requirements.txt "pyinstaller>=6.22" Pillow >>"$LOG" 2>&1 || fail "pip install"

echo "▸ Drawing icon…"
.venv/bin/python packaging/make_icon.py >>"$LOG" 2>&1 || fail "icon"

echo "▸ Building AniGUI.app (takes a minute or two)…"
.venv/bin/pyinstaller --noconfirm --clean --log-level WARN \
  --distpath build/dist --workpath build/work packaging/AniGUI.spec >>"$LOG" 2>&1 || fail "PyInstaller"

APP="build/dist/AniGUI.app"
[ -d "$APP" ] || fail "no app bundle produced"

echo "▸ Checking the build…"
"$APP/Contents/MacOS/AniGUI" --self-test >>"$LOG" 2>&1 || fail "self-test"

# Main Applications folder when we can write to it (admin accounts can), else ~/Applications.
DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
echo "▸ Installing to $DEST…"
mkdir -p "$DEST"
if pgrep -xq AniGUI; then
  echo "  AniGUI is open. Quit it (⌘Q) to finish installing…"
  while pgrep -xq AniGUI; do sleep 1; done
fi
rm -rf "$DEST/AniGUI.app"
ditto "$APP" "$DEST/AniGUI.app" || fail "copy to $DEST"
touch "$DEST/AniGUI.app"   # refresh Finder's icon cache
if [ "$DEST" = "/Applications" ] && [ -d "$HOME/Applications/AniGUI.app" ]; then
  rm -rf "$HOME/Applications/AniGUI.app"   # older install location; avoid two copies
fi

SIZE=$(du -sh "$DEST/AniGUI.app" | cut -f1)
echo "=== installed $DEST/AniGUI.app ($SIZE)" >>"$LOG"
echo
echo "✓ AniGUI.app installed in $DEST ($SIZE). Opening it now."
echo "  To keep it in the Dock: right-click its Dock icon → Options → Keep in Dock."
open "$DEST/AniGUI.app"
