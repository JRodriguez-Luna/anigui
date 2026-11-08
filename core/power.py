"""Keep the Mac (and its screen) awake while an episode plays in AniGUI.

IINA and mpv tell macOS "a video is playing" on their own. The built-in player has to do
it itself, or the screen dims and the Mac sleeps mid-episode (1.11). This holds a power
assertion while playing and lets go when paused, closed or AniGUI quits.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

_NO_DISPLAY_SLEEP = "PreventUserIdleDisplaySleep"
_LEVEL_ON = 255


class _MacPower:
    def __init__(self) -> None:
        iokit = ctypes.CDLL(ctypes.util.find_library("IOKit") or "/System/Library/Frameworks/IOKit.framework/IOKit")
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation")
                         or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self._cf_string = cf.CFStringCreateWithCString
        self._cf_string.restype = ctypes.c_void_p
        self._cf_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self._release_cf = cf.CFRelease
        self._release_cf.argtypes = [ctypes.c_void_p]
        self._create = iokit.IOPMAssertionCreateWithName
        self._create.restype = ctypes.c_int
        self._create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self._release = iokit.IOPMAssertionRelease
        self._release.restype = ctypes.c_int
        self._release.argtypes = [ctypes.c_uint32]

    def _cfstr(self, text: str):
        return self._cf_string(None, text.encode(), 0x08000100)   # kCFStringEncodingUTF8

    def hold(self, reason: str) -> int | None:
        kind, name = self._cfstr(_NO_DISPLAY_SLEEP), self._cfstr(reason)
        ident = ctypes.c_uint32(0)
        try:
            ok = self._create(kind, _LEVEL_ON, name, ctypes.byref(ident)) == 0
        finally:
            self._release_cf(kind)
            self._release_cf(name)
        return ident.value if ok else None

    def let_go(self, ident: int) -> None:
        self._release(ident)


class KeepAwake:
    """hold() while playing, release() when not. Safe to call either any number of times."""

    def __init__(self, backend=None) -> None:
        self.backend = backend
        if self.backend is None and sys.platform == "darwin":
            try:
                self.backend = _MacPower()
            except (OSError, AttributeError):
                self.backend = None
        self.ident: int | None = None

    @property
    def held(self) -> bool:
        return self.ident is not None

    def hold(self, reason: str = "Playing an episode in AniGUI") -> None:
        if self.ident is None and self.backend is not None:
            self.ident = self.backend.hold(reason)

    def release(self) -> None:
        if self.ident is not None and self.backend is not None:
            self.backend.let_go(self.ident)
        self.ident = None
