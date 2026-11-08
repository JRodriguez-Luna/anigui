"""Make a window float over every app and every Space (the pop-out player, 2.0).

Qt's "stay on top" keeps a window above other apps, but on macOS it still lives in one Space
and hides behind a full-screen app. This asks AppKit (through the Objective-C runtime, no
extra packages) to show it on all Spaces, beside full-screen apps too. Off macOS, or if
anything goes wrong, it does nothing: the window simply stays on top as Qt made it.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

CAN_JOIN_ALL_SPACES = 1 << 0
FULL_SCREEN_AUXILIARY = 1 << 8
FLOATING_LEVEL = 3          # NSFloatingWindowLevel (same as picture in picture)


def float_everywhere(win_id: int) -> bool:
    """win_id: QWidget.winId() of a top-level window (an NSView on macOS)."""
    if sys.platform != "darwin" or not win_id:
        return False
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        addr = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        send_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(addr)
        send_ulong = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(addr)
        send_long = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(addr)
        send_bool = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(addr)
        window = send_ptr(int(win_id), objc.sel_registerName(b"window"))
        if not window:
            return False
        send_ulong(window, objc.sel_registerName(b"setCollectionBehavior:"), CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY)
        send_long(window, objc.sel_registerName(b"setLevel:"), FLOATING_LEVEL)
        send_bool(window, objc.sel_registerName(b"setHidesOnDeactivate:"), False)
        return True
    except (OSError, AttributeError, ValueError, TypeError):
        return False
