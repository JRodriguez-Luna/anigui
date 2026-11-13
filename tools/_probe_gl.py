"""Temporary CI probe (never merged): which OpenGL setup lets mpv use VideoToolbox without
copying every frame, and does the picture still draw in a window like AniGUI's?"""
import os, subprocess, sys
sys.path.insert(0, ".")
def note(m): print(f"::notice title=gl::{m}"[:3800], flush=True)

CHILD = r'''
import os, sys, colorsys, resource, time; sys.path.insert(0, ".")
from PySide6.QtCore import QTimer, Qt, QCoreApplication
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout
mode = os.environ["PROBE_MODE"]
if mode.startswith("app-core"):
    f = QSurfaceFormat(); f.setVersion(4, 1); f.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(f)
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication(sys.argv)
from ui.player_view import VideoView
from core.player import embedded_options
from core.ani_cli import StreamInfo
win = QMainWindow(); central = QWidget(); win.setCentralWidget(central)
lay = QVBoxLayout(central); lay.addWidget(QLabel("AniGUI-like window, text up here")); lay.addStretch(1)
central.setStyleSheet("background:#0A0A0F; color:white")
opts, _ = embedded_options(StreamInfo(url="https://x.example/v", referrer=None, title=None), "Probe", None, None)
opts["ao"] = "null"
opts["hwdec"] = os.environ["PROBE_HWDEC"]
opts["log-file"] = os.environ["PROBE_LOG"]
v = VideoView(opts, os.environ["PROBE_CLIP"], [], central)
v.setGeometry(40, 60, 480, 270)
win.resize(700, 450); win.show(); v.show(); v.raise_()
t0 = {}
def start():
    r = resource.getrusage(resource.RUSAGE_SELF); t0["cpu"] = r.ru_utime + r.ru_stime; t0["wall"] = time.time()
def check():
    r = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (r.ru_utime + r.ru_stime - t0["cpu"]) / (time.time() - t0["wall"]) * 100
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
    print(f"RESULT hwdec_current={v.mpv.get('hwdec-current')} cpu={cpu:.0f}% colorful_fbo={sat/max(1,tot):.2f} "
          f"colorful_window={sat2/max(1,tot2):.2f} gl={v.format().majorVersion()}.{v.format().minorVersion()} "
          f"profile={v.format().profile().name} frames={v.mpv.get('estimated-frame-number')} drops={v.mpv.get('frame-drop-count')}",
          flush=True)
    v.close_engine(); app.quit()
QTimer.singleShot(2000, start)
QTimer.singleShot(8000, check)
app.exec()
'''
clip = os.path.abspath("probe.mp4")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=30:size=1920x1080:rate=24",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", clip], check=False)
note(f"clip exists: {os.path.exists(clip)}")
for mode, hwdec in (("default", "auto-safe"), ("app-core", "auto-safe"), ("default", "videotoolbox"),
                    ("app-core", "videotoolbox"), ("default", "no")):
    log = os.path.abspath(f"mpv-{mode}-{hwdec}.log")
    env = dict(os.environ, PROBE_MODE=mode, PROBE_HWDEC=hwdec, PROBE_LOG=log, PROBE_CLIP=clip, QT_QPA_PLATFORM="cocoa")
    try:
        out = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=120)
        res = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
        hw = ""
        if os.path.exists(log):
            lines = open(log, errors="replace").read().splitlines()
            keep = [l for l in lines if any(k in l for k in ("hwdec", "Hardware", "hardware", "interop", "OpenGL 3", "GL_VERSION", "[e]", "Using video"))]
            hw = " || ".join(keep[-14:])
        note(f"{mode}/{hwdec}: {res[0] if res else 'no result'} rc={out.returncode} | {out.stderr[-300:].replace(chr(10), ' | ')}")
        note(f"{mode}/{hwdec} log: {hw}")
    except Exception as exc:
        note(f"{mode}/{hwdec}: failed {exc!r}")
