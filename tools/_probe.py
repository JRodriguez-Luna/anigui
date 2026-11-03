"""Temporary CI probe (removed before release): does the video draw inside a window like
AniGUI's (a child of the main window), for each way of setting up OpenGL?"""
import os, subprocess, sys
sys.path.insert(0, ".")
def note(m): print(f"::notice title=video::{m}"[:3800], flush=True)

CHILD = r'''
import os, sys, colorsys; sys.path.insert(0, ".")
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout
if os.environ.get("ANIGUI_GL") == "app-core":
    f = QSurfaceFormat(); f.setVersion(4, 1); f.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(f)
app = QApplication(sys.argv)
from ui.player_view import VideoView
from core.player import embedded_options
from core.ani_cli import StreamInfo
win = QMainWindow(); central = QWidget(); win.setCentralWidget(central)
lay = QVBoxLayout(central); lay.addWidget(QLabel("AniGUI-like window, text up here")); lay.addStretch(1)
central.setStyleSheet("background:#0A0A0F; color:white")
opts, _ = embedded_options(StreamInfo(url="https://x.example/v", referrer=None, title=None), "Probe", None, None)
opts["ao"] = "null"
v = VideoView(opts, "av://lavfi:testsrc2=duration=20:size=640x360:rate=25", [], central)
v.setGeometry(40, 60, 480, 270)
win.resize(700, 450); win.show(); v.show(); v.raise_()
def check():
    img = v.grabFramebuffer()
    sat = tot = 0
    for x in range(4, img.width(), 13):
        for y in range(4, img.height(), 11):
            c = img.pixelColor(x, y); h, s, val = colorsys.rgb_to_hsv(c.redF(), c.greenF(), c.blueF())
            tot += 1; sat += (s > 0.5 and val > 0.4)
    w = win.grab().toImage()
    sat2 = tot2 = 0
    for x in range(50, 500, 13):
        for y in range(70, 320, 11):
            c = w.pixelColor(x, y); h, s, val = colorsys.rgb_to_hsv(c.redF(), c.greenF(), c.blueF())
            tot2 += 1; sat2 += (s > 0.5 and val > 0.4)
    print(f"RESULT colorful_fbo={sat/max(1,tot):.2f} colorful_window={sat2/max(1,tot2):.2f} "
          f"gl={v.format().majorVersion()}.{v.format().minorVersion()} profile={v.format().profile()} valid={v.isValid()} "
          f"vo={(v.mpv.get('video-out-params') or '')[:40]!r} pos={v.mpv.get('time-pos')}", flush=True)
    v.close_engine(); app.quit()
QTimer.singleShot(3500, check); app.exec()
'''
for mode in ("default", "widget-core", "app-core"):
    env = dict(os.environ, ANIGUI_GL=mode, QT_QPA_PLATFORM="cocoa")
    try:
        out = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=90)
        res = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
        note(f"{mode}: {res[0] if res else 'no result'} rc={out.returncode} | {out.stderr[-500:].replace(chr(10), ' | ')}")
    except Exception as exc:
        note(f"{mode}: failed {exc!r}")
