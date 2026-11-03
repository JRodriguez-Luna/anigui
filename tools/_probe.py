"""Temporary CI probe (removed before release): can AniGUI play inside its own window on a Mac?
Loads each libmpv it can find, draws a test video into a Qt OpenGL widget, and reports."""
import os, subprocess, sys
sys.path.insert(0, ".")
from core import libmpv
def note(m): print(f"::notice title=libmpv::{m}"[:3800], flush=True)

CHILD = r'''
import os, sys; sys.path.insert(0, ".")
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
if os.environ.get("CORE") == "1":
    f = QSurfaceFormat(); f.setVersion(3, 2); f.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(f)
from core import libmpv
class W(QOpenGLWidget):
    frame = Signal()
    def __init__(s):
        super().__init__(); s.m = libmpv.Mpv({"vo": "libmpv", "ao": "null", "keep-open": "yes", "hwdec": "auto-safe"}); s.r = None; s.err = None
        s.frame.connect(s.update, Qt.ConnectionType.QueuedConnection)
    def initializeGL(s):
        try:
            s.r = libmpv.GlRenderer(s.m, libmpv.gl_proc_address()); s.r.on_update(s.frame.emit)
        except Exception as e:
            s.err = repr(e)
        s.m.command("loadfile", "av://lavfi:testsrc=duration=8:size=320x240:rate=25")
    paints = 0
    def paintGL(s):
        W.paints += 1
        if s.r:
            r = s.devicePixelRatio(); s.r.render(s.defaultFramebufferObject(), int(s.width() * r), int(s.height() * r))
app = QApplication(sys.argv); w = W(); w.resize(320, 240); w.show(); w.raise_()
def check():
    img = w.grabFramebuffer()
    cols = {img.pixelColor(x, y).name() for x in range(5, img.width(), 37) for y in range(5, img.height(), 29)}
    g = w.grab().toImage()
    cols2 = {g.pixelColor(x, y).name() for x in range(5, g.width(), 37) for y in range(5, g.height(), 29)}
    print(f"RESULT api={libmpv.api_version()} colors={len(cols)} grab_colors={len(cols2)} paints={W.paints} "
          f"vo={w.m.get('video-out-params')!r:.80} pos={w.m.get('time-pos')} hwdec={w.m.get('hwdec-current')} "
          f"err={w.err} gl={w.format().majorVersion()}.{w.format().minorVersion()} valid={w.isValid()} "
          f"size={img.width()}x{img.height()} exposed={w.windowHandle().isExposed() if w.windowHandle() else None}", flush=True)
    app.quit()
QTimer.singleShot(2500, check); app.exec()
'''

paths = libmpv.candidates()
note(f"candidates: {paths}")
for path in paths:
    for core in ("0", "1"):
        env = dict(os.environ, ANIGUI_LIBMPV=path, CORE=core, QT_QPA_PLATFORM="cocoa")
        try:
            out = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=60)
            res = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
            note(f"{path} core={core}: {res[0] if res else 'no result'} rc={out.returncode} {out.stderr[-600:].replace(chr(10), ' | ') if not res or 'colors=1 ' in res[0] else ''}")
        except Exception as exc:
            note(f"{path} core={core}: failed {exc!r}")

