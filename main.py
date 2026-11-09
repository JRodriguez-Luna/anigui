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
        from core import alerts, ani_cli, aniskip, calendar, catalog, changelog, covers, mpv_ipc, player, self_update, setup, signer, signing, stats, store, updates  # noqa: F401
        from ui import alerts as ui_alerts, calendar_page, icons, main_window, search_page, settings_dialog, setup_dialog, signer_dialog, stats_page, update_dialog, whats_new  # noqa: F401
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
        # The built-in player: a release build carries its own libmpv
        from core import libmpv
        from ui import player_view, theater  # noqa: F401
        bundled = [c for c in libmpv.candidates() if str(ROOT) in c]
        if FROZEN and os.environ.get("ANIGUI_REQUIRE_LIBMPV") and not bundled:
            problems.append("built-in player: libmpv isn't in the app")
        if bundled:
            try:
                m = libmpv.Mpv({"vo": "null", "ao": "null", "idle": "yes"}, lib_path=bundled[0])
                print(f"self-test: built-in player ok (libmpv {'.'.join(map(str, libmpv.api_version()))})")
                m.close()
            except Exception as exc:  # noqa: BLE001
                problems.append(f"built-in player: {exc}")
        # Downloads (2.0): HLS pieces decrypt (AES-128) in the built app
        from core.downloads import decrypt
        sample = bytes.fromhex("634766a9edc6b39e18d79df46b64bb58")       # "AniGUI", zero key and IV
        try:
            if decrypt(bytes(16), bytes(16), sample) != b"AniGUI":
                raise ValueError("wrong result")
            print("self-test: Downloads ok (decrypt)")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Downloads: can't decrypt ({exc})")
        # Touch ID locks (2.0): reach LocalAuthentication without asking anything
        if sys.platform == "darwin":
            from core.touchid import TouchID
            tid = TouchID()
            if not tid.ok:
                problems.append("Touch ID: LocalAuthentication not reachable")
            else:
                print(f"self-test: Touch ID ok (can ask on this Mac: {tid.available()})")
            # Now Playing and media keys (2.0): reach MediaPlayer, register the keys, hand them back
            from core.nowplaying import NowPlaying
            np_ = NowPlaying()
            if not np_.ok or not np_.start(lambda *_a: None):
                problems.append("Now Playing: MediaPlayer not reachable")
            else:
                icon = ROOT / "packaging" / "AniGUI.png"
                np_.show("Episode 1", "AniGUI self-test", 12.0, 1420.0, False, str(icon) if icon.is_file() else None)
                np_.stop()
                print(f"self-test: Now Playing ok ({len(np_._keep) // 3} handlers)")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}")
    for p in problems:
        print(f"self-test: {p}")
    print("self-test: ok" if not problems else "self-test: FAILED")
    return 1 if problems else 0


SIGNER_HELP = """AniGUI release signer (for the publisher only)

  --signer-init        create your signing key (kept in the macOS Keychain) and print the public key
  --signer-install     check for releases to sign every 5 minutes, in the background
  --signer-check       check once now
  --signer-backup      print the private key, to keep in your password manager
  --signer-restore     put a backed-up key into the Keychain (paste it, then press Return)
  --signer-uninstall   stop the background checks
"""


def signer_main(command: str) -> int:
    from core import signer

    try:
        if command == "--signer-init":
            public = signer.init()
            print("Your signing key is in your Keychain (login keychain, \"AniGUI release signing key\").\n")
            print("Public key (safe to share; it goes into AniGUI):\n")
            print(f"    {public}\n")
            print("Next: back up the private key with --signer-backup, then run --signer-install.")
        elif command == "--signer-backup":
            print("macOS will ask for your password to release the key.\n")
            print(signer.read_key())
            print("\nKeep this in your password manager. Anyone with it can sign AniGUI updates. "
                  "Clear this Terminal window afterwards (Cmd+K).")
        elif command == "--signer-restore":
            key = sys.stdin.readline().strip()
            from core import signing
            print(f"Restored. Public key: {signing.public_key_of(key)}")
            signer.store_key(key)
        elif command == "--signer-install":
            path = signer.install_agent()
            print(f"Background checks are on ({path}). You'll get a window when a release is ready to sign.")
        elif command == "--signer-uninstall":
            signer.uninstall_agent()
            print("Background checks are off.")
        elif command == "--signer-check":
            return signer_check()
        else:
            print(SIGNER_HELP)
            return 1
    except signer.SignerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def signer_check() -> int:
    """One look at GitHub; a review window for each release waiting to be signed."""
    from core import signer

    try:
        pending = signer.pending_releases()
    except Exception as exc:  # noqa: BLE001 - offline etc.: try again next time
        print(f"signer: couldn't check GitHub: {exc}")
        return 0
    if not pending:
        return 0
    from PySide6.QtWidgets import QApplication

    from ui.signer_dialog import SignDialog
    from ui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    for p in pending:
        print(f"signer: {p.tag} is waiting to be signed")
        review = signer.prepare(p)
        SignDialog(review).exec()
    return 0


def refresh_signer_agent() -> None:
    """The publisher's background check (only set up on the publisher's Mac): reload it
    after an update so macOS doesn't refuse to start the new app from the old one's."""
    if sys.platform != "darwin":
        return
    try:
        from core import signer

        if signer.refresh_agent():
            print("signer: background check reloaded for this version")
    except Exception as exc:  # noqa: BLE001 - never stop the app from opening
        print(f"signer: couldn't reload the background check: {exc}")


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    command = next((a for a in sys.argv[1:] if a.startswith("--signer")), None)
    if command:
        return signer_main(command)
    setup_logging()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from ui.context import AppContext
    from ui.main_window import MainWindow
    from ui.theme import apply_theme

    # One family of OpenGL contexts for every window: the video keeps its context when it
    # moves into the pop-out window and back, so it plays straight through (2.0)
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("AniGUI")
    app.setApplicationDisplayName("AniGUI")
    app.setOrganizationName("AniGUI")
    if ICON.is_file():
        app.setWindowIcon(QIcon(str(ICON)))
    apply_theme(app)

    refresh_signer_agent()
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
