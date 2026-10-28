#!/usr/bin/env python3
"""AniGUI — desktop front end for ani-cli.

    python main.py               # run the app
    python main.py --self-test   # check the install without opening a window
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import traceback
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

LOG_DIR = Path.home() / "Library" / "Logs" / "AniGUI"
ICON = ROOT / "packaging" / "AniGUI.png"


def setup_logging() -> None:
    """A .app has no terminal: send output and uncaught errors to ~/Library/Logs/AniGUI."""
    if not FROZEN:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "anigui.log", "a", buffering=1, encoding="utf-8")
    log.write(f"\n=== AniGUI started {dt.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    log.flush()
    os.dup2(log.fileno(), 1)  # also catch Qt's own warnings, which bypass sys.stderr
    os.dup2(log.fileno(), 2)
    sys.stdout = sys.stderr = log

    def hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb, file=log)

    sys.excepthook = hook


def self_test() -> int:
    """Import everything and check bundled files. Used by the build script."""
    problems = []
    try:
        from PySide6.QtNetwork import QLocalSocket  # noqa: F401
        from core import ani_cli, catalog, covers, mpv_ipc, player, setup, store, updates  # noqa: F401
        from ui import main_window, setup_dialog  # noqa: F401
        import certifi

        if not Path(certifi.where()).is_file():
            problems.append("certifi CA bundle missing")
        if not (ROOT / "core" / "bin" / "anigui-mpv-shim").is_file():
            problems.append("ani-cli player shim missing")
        if not ICON.is_file():
            problems.append("icon missing")
        shim = ani_cli.install_shim()
        if not os.access(shim, os.X_OK):
            problems.append(f"shim not executable: {shim}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}")
    for p in problems:
        print(f"self-test: {p}")
    print("self-test: ok" if not problems else "self-test: FAILED")
    return 1 if problems else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    setup_logging()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from ui.context import AppContext
    from ui.main_window import MainWindow
    from ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("AniGUI")
    app.setApplicationDisplayName("AniGUI")
    app.setOrganizationName("AniGUI")
    if ICON.is_file():
        app.setWindowIcon(QIcon(str(ICON)))
    apply_theme(app)

    ctx = AppContext.create()
    window = MainWindow(ctx)
    window.show()
    window.start()
    code = app.exec()

    ctx.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    # Worker threads may still be waiting on a slow network call; don't hang on quit.
    # All database writes are already committed, so skipping interpreter teardown is safe.
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
