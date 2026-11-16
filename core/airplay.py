"""TV mode (2.1): send an episode to an AirPlay TV with macOS's own AVFoundation.

An AVPlayer plays the relay's playlist; macOS's AirPlay picker (AVRoutePickerView, the same
button QuickTime and Safari show) lists the TVs on your Wi-Fi. Pick one and the TV fetches the
stream itself ("external playback"): this Mac becomes the remote. Everything here is the
Objective-C runtime through ctypes, so no extra packages. Off a Mac, `ok` is False and nothing
here does anything.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from ctypes import CFUNCTYPE, Structure, c_bool, c_char_p, c_double, c_float, c_int, c_int32, c_int64, c_long, \
    c_uint32, c_ulong, c_void_p

TIME_CONTROL = {0: "paused", 1: "waiting", 2: "playing"}
STATUS = {0: "unknown", 1: "ready", 2: "failed"}


class CMTime(Structure):
    _fields_ = [("value", c_int64), ("timescale", c_int32), ("flags", c_uint32), ("epoch", c_int64)]

    @property
    def seconds(self) -> float | None:
        if not self.flags & 1 or not self.timescale:        # kCMTimeFlags_Valid
            return None
        return self.value / self.timescale


class CGPoint(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class CGSize(Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class CGRect(Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


class AirPlayer:
    def __init__(self) -> None:
        self.ok = False
        self.player: int | None = None
        self.picker: int | None = None
        self.url = ""
        if sys.platform != "darwin":
            return
        try:
            self._objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
            for fw in ("Foundation", "AppKit", "CoreMedia", "AVFoundation", "AVKit"):
                ctypes.cdll.LoadLibrary(f"/System/Library/Frameworks/{fw}.framework/{fw}")
            o = self._objc
            o.objc_getClass.restype = c_void_p
            o.objc_getClass.argtypes = [c_char_p]
            o.sel_registerName.restype = c_void_p
            o.sel_registerName.argtypes = [c_char_p]
            addr = ctypes.cast(o.objc_msgSend, c_void_p).value
            self._send = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(addr)
            self._send_ptr = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p)(addr)
            self._send_2ptr = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)(addr)
            self._send_str = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_char_p)(addr)
            self._send_bool = CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(addr)
            self._send_float = CFUNCTYPE(None, c_void_p, c_void_p, c_float)(addr)
            self._send_ulong = CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(addr)
            self._send_rect = CFUNCTYPE(c_void_p, c_void_p, c_void_p, CGRect)(addr)
            self._send_time = CFUNCTYPE(None, c_void_p, c_void_p, CMTime)(addr)
            self._get_bool = CFUNCTYPE(c_bool, c_void_p, c_void_p)(addr)
            self._get_float = CFUNCTYPE(c_float, c_void_p, c_void_p)(addr)
            self._get_long = CFUNCTYPE(c_long, c_void_p, c_void_p)(addr)
            self._get_int = CFUNCTYPE(c_int, c_void_p, c_void_p)(addr)
            self._get_str = CFUNCTYPE(c_char_p, c_void_p, c_void_p)(addr)
            self._get_time = CFUNCTYPE(CMTime, c_void_p, c_void_p)(addr)
            self._send_point = CFUNCTYPE(CGPoint, c_void_p, c_void_p, CGPoint, c_void_p)(addr)
            self._get_ulong = CFUNCTYPE(c_ulong, c_void_p, c_void_p)(addr)
            self._mouse_event = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_ulong, CGPoint, c_ulong, c_double, c_long,
                                          c_void_p, c_long, c_long, c_float)(addr)
            self._cls = {n: o.objc_getClass(n.encode()) for n in (
                "AVPlayer", "AVPlayerItem", "AVURLAsset", "AVRoutePickerView", "NSURL", "NSString", "NSView",
                "NSColor", "NSEvent", "NSAppearance")}
            self.ok = all(self._cls.values())
        except (OSError, AttributeError, ValueError):
            self.ok = False

    def _sel(self, name: str):
        return self._objc.sel_registerName(name.encode())

    def _string(self, text: str):
        return self._send_str(self._cls["NSString"], self._sel("stringWithUTF8String:"), text.encode())

    def _text(self, nsstring) -> str:
        if not nsstring:
            return ""
        raw = self._get_str(nsstring, self._sel("UTF8String"))
        return raw.decode("utf-8", "replace") if raw else ""

    # -- playing -----------------------------------------------------------------------------------

    def load(self, url: str, start: float | None = None, play: bool = True) -> bool:
        """An AVPlayer on this address (an HLS playlist), allowed to play on a TV."""
        if not self.ok:
            return False
        self.close()
        self.url = url
        nsurl = self._send_ptr(self._cls["NSURL"], self._sel("URLWithString:"), self._string(url))
        if not nsurl:
            return False
        asset = self._send_2ptr(self._cls["AVURLAsset"], self._sel("URLAssetWithURL:options:"), nsurl, None)
        item = self._send_ptr(self._cls["AVPlayerItem"], self._sel("playerItemWithAsset:"), asset)
        player = self._send_ptr(self._cls["AVPlayer"], self._sel("playerWithPlayerItem:"), item)
        if not player:
            return False
        self._send(player, self._sel("retain"))
        self._send_bool(player, self._sel("setAllowsExternalPlayback:"), True)
        self._send_bool(player, self._sel("setUsesExternalPlaybackWhileExternalScreenIsActive:"), True)
        self.player = player
        if self.picker and self._responds(self.picker, "setPlayer:"):
            self._send_ptr(self.picker, self._sel("setPlayer:"), player)
        if start:
            self.seek(start)
        if play:
            self.play()
        return True

    def play(self) -> None:
        if self.player:
            self._send(self.player, self._sel("play"))

    def pause(self) -> None:
        if self.player:
            self._send(self.player, self._sel("pause"))

    def seek(self, seconds: float) -> None:
        if self.player:
            self._send_time(self.player, self._sel("seekToTime:"), CMTime(int(seconds * 1000), 1000, 1, 0))

    def set_volume(self, level: float) -> None:
        if self.player:
            self._send_float(self.player, self._sel("setVolume:"), max(0.0, min(1.0, level)))

    # -- the AirPlay button ------------------------------------------------------------------------

    def attach_picker(self, nsview: int, x: float, y: float, w: float, h: float) -> bool:
        """macOS's AirPlay picker button inside a Qt widget (its winId() is an NSView)."""
        if not self.ok or not nsview:
            return False
        picker = self._send_rect(self._send(self._cls["AVRoutePickerView"], self._sel("alloc")),
                                 self._sel("initWithFrame:"), CGRect(CGPoint(x, y), CGSize(w, h)))
        if not picker:
            return False
        self._send_ptr(nsview, self._sel("addSubview:"), picker)
        # Optional looks, only where this macOS has them (macOS 27 lacks the color setter and
        # crashed on it): a bordered button, drawn for a dark window
        if self._responds(picker, "setRoutePickerButtonBordered:"):
            self._send_bool(picker, self._sel("setRoutePickerButtonBordered:"), True)
        dark = self._send_ptr(self._cls["NSAppearance"], self._sel("appearanceNamed:"),
                              self._string("NSAppearanceNameDarkAqua"))
        if dark and self._responds(picker, "setAppearance:"):
            self._send_ptr(picker, self._sel("setAppearance:"), dark)
        if self._responds(picker, "setRoutePickerButtonColor:"):
            self._send_ptr(picker, self._sel("setRoutePickerButtonColor:"),
                           self._send(self._cls["NSColor"], self._sel("whiteColor")))
        if self.player and self._responds(picker, "setPlayer:"):
            self._send_ptr(picker, self._sel("setPlayer:"), self.player)
        self.picker = picker
        return True

    def press_picker(self) -> str:
        """Open the picker's menu without a mouse click (a click into the picker from a Qt
        window didn't reach it). Returns what was done."""
        if not self.picker:
            return "no picker"
        subviews = self._send(self.picker, self._sel("subviews"))
        count = int(self._get_ulong(subviews, self._sel("count"))) if subviews else 0
        for i in range(count):
            view = self._send_ptr(subviews, self._sel("objectAtIndex:"), c_void_p(i))
            if view and self._responds(view, "performClick:"):
                self._send_ptr(view, self._sel("performClick:"), None)
                return "performClick on the picker's button"
        # No button inside: a synthetic click on the picker itself
        window = self._send(self.picker, self._sel("window"))
        if not window:
            return "picker has no window"
        bounds_mid = CGPoint(24, 18)
        at = self._send_point(self.picker, self._sel("convertPoint:toView:"), bounds_mid, None)
        number = int(self._get_long(window, self._sel("windowNumber")))
        down = self._mouse_event(self._cls["NSEvent"], self._sel(
            "mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:"),
            1, at, 0, 0.0, number, None, 0, 1, 1.0)
        up = self._mouse_event(self._cls["NSEvent"], self._sel(
            "mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:"),
            2, at, 0, 0.0, number, None, 0, 1, 0.0)
        self._send_ptr(self.picker, self._sel("mouseDown:"), down)
        self._send_ptr(self.picker, self._sel("mouseUp:"), up)
        return "synthetic click on the picker"

    def _responds(self, obj, selector: str) -> bool:
        fn = CFUNCTYPE(c_bool, c_void_p, c_void_p, c_void_p)(ctypes.cast(self._objc.objc_msgSend, c_void_p).value)
        return bool(fn(obj, self._sel("respondsToSelector:"), self._sel(selector)))

    def move_picker(self, x: float, y: float, w: float, h: float) -> None:
        if self.picker:
            self._send_rect(self.picker, self._sel("setFrame:"), CGRect(CGPoint(x, y), CGSize(w, h)))

    # -- how it's going ----------------------------------------------------------------------------

    def status(self) -> dict:
        """external (on a TV?), state, time, duration, rate, waiting, error, item."""
        out = {"external": False, "state": "none", "time": None, "duration": None, "rate": 0.0,
               "waiting": "", "error": "", "item": "none"}
        p = self.player
        if not self.ok or not p:
            return out
        out["external"] = bool(self._get_bool(p, self._sel("isExternalPlaybackActive")))
        out["state"] = TIME_CONTROL.get(int(self._get_long(p, self._sel("timeControlStatus"))), "?")
        out["rate"] = float(self._get_float(p, self._sel("rate")))
        out["waiting"] = self._text(self._send(p, self._sel("reasonForWaitingToPlay")))
        err = self._send(p, self._sel("error"))
        item = self._send(p, self._sel("currentItem"))
        if item:
            out["item"] = STATUS.get(int(self._get_long(item, self._sel("status"))), "?")
            err = err or self._send(item, self._sel("error"))
            out["time"] = self._get_time(item, self._sel("currentTime")).seconds
            out["duration"] = self._get_time(item, self._sel("duration")).seconds
        if err:
            out["error"] = self._text(self._send(err, self._sel("localizedDescription")))
        return out

    def close(self) -> None:
        if self.player:
            self.pause()
            if self.picker and self._responds(self.picker, "setPlayer:"):
                self._send_ptr(self.picker, self._sel("setPlayer:"), None)
            self._send(self.player, self._sel("release"))
            self.player = None

    def detach_picker(self) -> None:
        if self.picker:
            self._send(self.picker, self._sel("removeFromSuperview"))
            self._send(self.picker, self._sel("release"))
            self.picker = None
