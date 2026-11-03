"""A small ctypes binding to libmpv, for playing inside AniGUI's own window.

Only what the built-in player needs: options, commands, properties, events, and the
OpenGL render API. The library is found at run time (AniGUI's own copy first, then
IINA's, then Homebrew's), so nothing here is imported unless the built-in player is used.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import sys
from ctypes import (CFUNCTYPE, POINTER, Structure, byref, c_char_p, c_double, c_int, c_int64, c_uint64,
                    c_void_p)
from pathlib import Path

# mpv_format
FORMAT_NONE, FORMAT_STRING, FORMAT_FLAG, FORMAT_INT64, FORMAT_DOUBLE = 0, 1, 3, 4, 5
# mpv_event_id
EVENT_NONE, EVENT_SHUTDOWN, EVENT_START_FILE, EVENT_END_FILE, EVENT_FILE_LOADED = 0, 1, 6, 7, 8
EVENT_VIDEO_RECONFIG, EVENT_PLAYBACK_RESTART, EVENT_PROPERTY_CHANGE = 17, 21, 22
# mpv_render_param_type
RENDER_INVALID, RENDER_API_TYPE, RENDER_OPENGL_INIT, RENDER_OPENGL_FBO, RENDER_FLIP_Y = 0, 1, 2, 3, 4
RENDER_UPDATE_FRAME = 1


class LibMpvError(RuntimeError):
    pass


class _Event(Structure):
    _fields_ = [("event_id", c_int), ("error", c_int), ("reply_userdata", c_uint64), ("data", c_void_p)]


class _EventProperty(Structure):
    _fields_ = [("name", c_char_p), ("format", c_int), ("data", c_void_p)]


class _EventEndFile(Structure):
    _fields_ = [("reason", c_int), ("error", c_int)]


class _RenderParam(Structure):
    _fields_ = [("type", c_int), ("data", c_void_p)]


GET_PROC = CFUNCTYPE(c_void_p, c_void_p, c_char_p)
UPDATE_FN = CFUNCTYPE(None, c_void_p)
WAKEUP_FN = CFUNCTYPE(None, c_void_p)


class _GlInit(Structure):
    # extra_exts was dropped in client API 2.0; a trailing NULL is harmless either way
    _fields_ = [("get_proc_address", GET_PROC), ("ctx", c_void_p), ("extra_exts", c_char_p)]


class _Fbo(Structure):
    _fields_ = [("fbo", c_int), ("w", c_int), ("h", c_int), ("internal_format", c_int)]


def candidates() -> list[str]:
    """Where libmpv may be, best first: bundled with AniGUI, inside IINA, Homebrew."""
    found: list[str] = []
    env = os.environ.get("ANIGUI_LIBMPV")
    if env:
        found.append(env)
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    found += sorted(glob.glob(str(here / "libmpv" / "libmpv*.dylib")))
    for app in ("/Applications/IINA.app", str(Path.home() / "Applications" / "IINA.app")):
        found += sorted(glob.glob(f"{app}/Contents/Frameworks/libmpv*.dylib"), reverse=True)
    for prefix in ("/opt/homebrew", "/usr/local"):
        found += sorted(glob.glob(f"{prefix}/lib/libmpv*.dylib"), reverse=True)
    found += sorted(glob.glob("/usr/lib/*/libmpv.so*"))  # Linux (development only)
    seen, out = set(), []
    for path in found:
        if path not in seen and os.path.exists(path):
            seen.add(path)
            out.append(path)
    return out


_lib: ctypes.CDLL | None = None
_lib_path: str | None = None


def load(path: str | None = None) -> ctypes.CDLL:
    """Load libmpv once (the first candidate that loads)."""
    global _lib, _lib_path
    if _lib is not None and (path is None or path == _lib_path):
        return _lib
    errors = []
    for p in ([path] if path else candidates()):
        try:
            lib = ctypes.CDLL(p, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        except OSError as exc:
            errors.append(f"{p}: {exc}")
            continue
        _declare(lib)
        _lib, _lib_path = lib, p
        return lib
    raise LibMpvError("The built-in player isn't available (no libmpv found)."
                      + (f" {'; '.join(errors)}" if errors else ""))


def loaded_path() -> str | None:
    return _lib_path


def _declare(lib: ctypes.CDLL) -> None:
    sig = {
        "mpv_client_api_version": (ctypes.c_ulong, []),
        "mpv_create": (c_void_p, []),
        "mpv_initialize": (c_int, [c_void_p]),
        "mpv_terminate_destroy": (None, [c_void_p]),
        "mpv_set_option_string": (c_int, [c_void_p, c_char_p, c_char_p]),
        "mpv_set_property_string": (c_int, [c_void_p, c_char_p, c_char_p]),
        "mpv_get_property": (c_int, [c_void_p, c_char_p, c_int, c_void_p]),
        "mpv_get_property_string": (c_void_p, [c_void_p, c_char_p]),
        "mpv_free": (None, [c_void_p]),
        "mpv_command": (c_int, [c_void_p, POINTER(c_char_p)]),
        "mpv_command_async": (c_int, [c_void_p, c_uint64, POINTER(c_char_p)]),
        "mpv_observe_property": (c_int, [c_void_p, c_uint64, c_char_p, c_int]),
        "mpv_wait_event": (POINTER(_Event), [c_void_p, c_double]),
        "mpv_set_wakeup_callback": (None, [c_void_p, WAKEUP_FN, c_void_p]),
        "mpv_error_string": (c_char_p, [c_int]),
        "mpv_render_context_create": (c_int, [POINTER(c_void_p), c_void_p, POINTER(_RenderParam)]),
        "mpv_render_context_set_update_callback": (None, [c_void_p, UPDATE_FN, c_void_p]),
        "mpv_render_context_update": (c_uint64, [c_void_p]),
        "mpv_render_context_render": (c_int, [c_void_p, POINTER(_RenderParam)]),
        "mpv_render_context_report_swap": (None, [c_void_p]),
        "mpv_render_context_free": (None, [c_void_p]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args


def api_version() -> tuple[int, int]:
    v = load().mpv_client_api_version()
    return v >> 16, v & 0xFFFF


def _b(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


class Mpv:
    """One mpv instance. Not thread-safe except where libmpv says so; AniGUI calls it from
    the main thread and drains events when the wakeup callback fires."""

    def __init__(self, options: dict[str, str] | None = None, lib_path: str | None = None) -> None:
        self.lib = load(lib_path)
        self.handle = self.lib.mpv_create()
        if not self.handle:
            raise LibMpvError("libmpv couldn't start.")
        for key, value in (options or {}).items():
            self.set_option(key, value)
        self._check(self.lib.mpv_initialize(self.handle), "initialize")
        self._wakeup = None
        self._observed: dict[int, tuple[str, int]] = {}

    def _check(self, rc: int, what: str) -> int:
        if rc < 0:
            raise LibMpvError(f"mpv {what}: {self.lib.mpv_error_string(rc).decode(errors='replace')}")
        return rc

    def set_option(self, name: str, value) -> None:
        self._check(self.lib.mpv_set_option_string(self.handle, _b(name), _b(value)), f"option {name}")

    def set(self, name: str, value) -> None:
        if isinstance(value, bool):
            value = "yes" if value else "no"
        self._check(self.lib.mpv_set_property_string(self.handle, _b(name), _b(value)), f"set {name}")

    def get(self, name: str) -> str | None:
        ptr = self.lib.mpv_get_property_string(self.handle, _b(name))
        if not ptr:
            return None
        try:
            return ctypes.string_at(ptr).decode("utf-8", "replace")
        finally:
            self.lib.mpv_free(ptr)

    def get_double(self, name: str) -> float | None:
        out = c_double()
        rc = self.lib.mpv_get_property(self.handle, _b(name), FORMAT_DOUBLE, byref(out))
        return out.value if rc >= 0 else None

    def command(self, *args) -> None:
        arr = (c_char_p * (len(args) + 1))(*[_b(a) for a in args], None)
        self._check(self.lib.mpv_command(self.handle, arr), f"command {args[0]}")

    def command_async(self, *args) -> None:
        arr = (c_char_p * (len(args) + 1))(*[_b(a) for a in args], None)
        self._check(self.lib.mpv_command_async(self.handle, 0, arr), f"command {args[0]}")

    def observe(self, ident: int, name: str, fmt: int = FORMAT_DOUBLE) -> None:
        self._observed[ident] = (name, fmt)
        self._check(self.lib.mpv_observe_property(self.handle, ident, _b(name), fmt), f"observe {name}")

    def on_wakeup(self, fn) -> None:
        """fn() is called from an mpv thread when events are waiting: hand it to the UI thread."""
        self._wakeup = WAKEUP_FN(lambda _ctx: fn())
        self.lib.mpv_set_wakeup_callback(self.handle, self._wakeup, None)

    def events(self):
        """Every waiting event, as (kind, data): ("property", (name, value)), ("end", reason),
        ("loaded", None), ("shutdown", None), ("restart", None)."""
        while True:
            ev = self.lib.mpv_wait_event(self.handle, 0).contents
            eid = ev.event_id
            if eid == EVENT_NONE:
                return
            if eid == EVENT_PROPERTY_CHANGE and ev.data:
                prop = ctypes.cast(ev.data, POINTER(_EventProperty)).contents
                name = prop.name.decode()
                value = None
                if prop.data:
                    if prop.format == FORMAT_DOUBLE:
                        value = ctypes.cast(prop.data, POINTER(c_double)).contents.value
                    elif prop.format == FORMAT_FLAG:
                        value = bool(ctypes.cast(prop.data, POINTER(c_int)).contents.value)
                    elif prop.format == FORMAT_INT64:
                        value = ctypes.cast(prop.data, POINTER(c_int64)).contents.value
                    elif prop.format == FORMAT_STRING:
                        value = ctypes.cast(prop.data, POINTER(c_char_p)).contents.value
                        value = value.decode("utf-8", "replace") if value is not None else None
                yield "property", (name, value)
            elif eid == EVENT_END_FILE:
                reason = ctypes.cast(ev.data, POINTER(_EventEndFile)).contents.reason if ev.data else 0
                yield "end", reason
            elif eid == EVENT_FILE_LOADED:
                yield "loaded", None
            elif eid == EVENT_PLAYBACK_RESTART:
                yield "restart", None
            elif eid == EVENT_SHUTDOWN:
                yield "shutdown", None
                return

    def close(self) -> None:
        if self.handle:
            self.lib.mpv_terminate_destroy(self.handle)
            self.handle = None


class GlRenderer:
    """mpv drawing into the current OpenGL context (a QOpenGLWidget's)."""

    def __init__(self, mpv: Mpv, get_proc_address) -> None:
        self.mpv = mpv
        lib = mpv.lib
        self._proc = GET_PROC(lambda _ctx, name: get_proc_address(name) or 0)
        self._init = _GlInit(self._proc, None, None)
        params = (_RenderParam * 3)(
            _RenderParam(RENDER_API_TYPE, ctypes.cast(c_char_p(b"opengl"), c_void_p)),
            _RenderParam(RENDER_OPENGL_INIT, ctypes.cast(ctypes.pointer(self._init), c_void_p)),
            _RenderParam(RENDER_INVALID, None),
        )
        self._api = c_char_p(b"opengl")
        params[0].data = ctypes.cast(self._api, c_void_p)
        self.ctx = c_void_p()
        rc = lib.mpv_render_context_create(byref(self.ctx), mpv.handle, params)
        if rc < 0:
            raise LibMpvError(f"mpv render: {lib.mpv_error_string(rc).decode(errors='replace')}")
        self._update = None

    def on_update(self, fn) -> None:
        """fn() is called from an mpv thread when a new frame is ready."""
        self._update = UPDATE_FN(lambda _ctx: fn())
        self.mpv.lib.mpv_render_context_set_update_callback(self.ctx, self._update, None)

    def render(self, fbo: int, width: int, height: int) -> None:
        lib = self.mpv.lib
        lib.mpv_render_context_update(self.ctx)
        target = _Fbo(fbo, width, height, 0)
        flip = c_int(1)
        params = (_RenderParam * 3)(
            _RenderParam(RENDER_OPENGL_FBO, ctypes.cast(ctypes.pointer(target), c_void_p)),
            _RenderParam(RENDER_FLIP_Y, ctypes.cast(ctypes.pointer(flip), c_void_p)),
            _RenderParam(RENDER_INVALID, None),
        )
        lib.mpv_render_context_render(self.ctx, params)

    def report_swap(self) -> None:
        self.mpv.lib.mpv_render_context_report_swap(self.ctx)

    def close(self) -> None:
        if self.ctx:
            self.mpv.lib.mpv_render_context_set_update_callback(self.ctx, UPDATE_FN(0), None)
            self.mpv.lib.mpv_render_context_free(self.ctx)
            self.ctx = c_void_p()


def gl_proc_address():
    """get_proc_address for macOS: every GL function lives in the OpenGL framework."""
    if sys.platform == "darwin":
        gl = ctypes.CDLL("/System/Library/Frameworks/OpenGL.framework/OpenGL")
    else:
        gl = ctypes.CDLL(ctypes.util.find_library("GL") or "libGL.so.1")

    def get(name: bytes) -> int:
        try:
            return ctypes.cast(getattr(gl, name.decode()), c_void_p).value or 0
        except AttributeError:
            return 0
    return get
