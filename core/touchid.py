"""Touch ID (or your Mac's password) through macOS LocalAuthentication (2.0).

Talks to LAContext through the Objective-C runtime with ctypes, so no extra packages. The
policy used is "device owner authentication": Touch ID or Apple Watch when there is one, and
your login password otherwise, the same sheet System Settings shows. Nothing about it leaves
the Mac; AniGUI only learns yes or no.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import threading
from ctypes import CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_int, c_long, c_ulong, c_void_p
from typing import Callable

POLICY_OWNER = 2              # LAPolicyDeviceOwnerAuthentication
_BLOCK_IS_GLOBAL = 1 << 28
_REPLY = CFUNCTYPE(None, c_void_p, c_bool, c_void_p)     # ^(BOOL success, NSError *error)


class _Descriptor(Structure):
    _fields_ = [("reserved", c_ulong), ("size", c_ulong)]


class _Block(Structure):
    _fields_ = [("isa", c_void_p), ("flags", c_int), ("reserved", c_int),
                ("invoke", c_void_p), ("descriptor", POINTER(_Descriptor))]


class TouchID:
    """ask(reason, done) shows the sheet; done(bool) is called on a background thread."""

    def __init__(self) -> None:
        self.ok = False
        self._pending: dict[int, tuple] = {}
        self._lock = threading.Lock()
        if sys.platform != "darwin":
            return
        try:
            self._objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/LocalAuthentication.framework/LocalAuthentication")
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
            system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            self._global_block = ctypes.addressof(c_void_p.in_dll(system, "_NSConcreteGlobalBlock"))
            o = self._objc
            o.objc_getClass.restype = c_void_p
            o.objc_getClass.argtypes = [c_char_p]
            o.sel_registerName.restype = c_void_p
            o.sel_registerName.argtypes = [c_char_p]
            addr = ctypes.cast(o.objc_msgSend, c_void_p).value
            self._send = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(addr)
            self._send_str = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_char_p)(addr)
            self._can = CFUNCTYPE(c_bool, c_void_p, c_void_p, c_long, c_void_p)(addr)
            self._evaluate = CFUNCTYPE(None, c_void_p, c_void_p, c_long, c_void_p, c_void_p)(addr)
            self._la = o.objc_getClass(b"LAContext")
            self._nsstring = o.objc_getClass(b"NSString")
            self.ok = bool(self._la and self._nsstring)
        except (OSError, AttributeError, ValueError):
            self.ok = False

    def _sel(self, name: str):
        return self._objc.sel_registerName(name.encode())

    def _context(self):
        ctx = self._send(self._la, self._sel("alloc"))
        return self._send(ctx, self._sel("init"))

    def available(self) -> bool:
        """Can this Mac ask (Touch ID, Apple Watch or a password)?"""
        if not self.ok:
            return False
        ctx = self._context()
        try:
            return bool(self._can(ctx, self._sel("canEvaluatePolicy:error:"), POLICY_OWNER, None))
        finally:
            self._send(ctx, self._sel("release"))

    def ask(self, reason: str, done: Callable[[bool], None]) -> None:
        if not self.ok:
            done(False)
            return
        ctx = self._context()
        text = self._send_str(self._nsstring, self._sel("stringWithUTF8String:"), reason.encode())

        def reply(_block, success, _error):
            with self._lock:
                held = self._pending.pop(key, None)
            try:
                done(bool(success))
            finally:
                if held is not None:
                    self._send(held[0], self._sel("release"))

        invoke = _REPLY(reply)
        desc = _Descriptor(0, ctypes.sizeof(_Block))
        block = _Block(self._global_block, _BLOCK_IS_GLOBAL, 0, ctypes.cast(invoke, c_void_p).value,
                       ctypes.pointer(desc))
        key = id(block)
        with self._lock:
            self._pending[key] = (ctx, invoke, desc, block)     # alive until macOS answers
        self._evaluate(ctx, self._sel("evaluatePolicy:localizedReason:reply:"), POLICY_OWNER, text,
                       ctypes.addressof(block))
