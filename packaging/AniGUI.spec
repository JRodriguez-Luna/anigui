# PyInstaller spec for AniGUI.app (one-folder bundle, macOS).
#   pyinstaller --noconfirm packaging/AniGUI.spec
# ani-cli, fzf, curl and IINA/mpv stay external: they come from Homebrew at run time.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = "1.0.0"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "core" / "bin" / "anigui-mpv-shim"), "core/bin"),
        (str(ROOT / "packaging" / "AniGUI.png"), "packaging"),
    ],
    hiddenimports=["PySide6.QtNetwork"],
    excludes=[
        "pytest", "tkinter", "unittest", "pydoc_data",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AniGUI",
    console=False,
    argv_emulation=False,
    target_arch=None,          # build for the machine it runs on (arm64 on Apple silicon)
    codesign_identity=None,    # ad-hoc signature; fine for an app built on this Mac
    icon=str(ROOT / "packaging" / "AniGUI.icns"),
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AniGUI")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AniGUI.app",
        icon=str(ROOT / "packaging" / "AniGUI.icns"),
        bundle_identifier="dev.jrodriguez-luna.anigui",
        version=VERSION,
        info_plist={
            "CFBundleName": "AniGUI",
            "CFBundleDisplayName": "AniGUI",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSApplicationCategoryType": "public.app-category.entertainment",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
