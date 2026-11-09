"""Now Playing and your Mac's media keys (2.0).

Tells macOS what the built-in player is playing (Control Center, the lock screen, AirPods and
the keyboard's ⏯ ⏭ keys), through MediaPlayer's MPNowPlayingInfoCenter and
MPRemoteCommandCenter, with the Objective-C runtime and ctypes, so no extra packages. This
stays on your Mac: macOS shows it, nothing is sent anywhere.

Off macOS, or if anything here is missing, NowPlaying.ok is False and every call does nothing.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from ctypes import CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double, c_int, c_long, c_ulong, c_void_p
from typing import Callable

STATE_PLAYING, STATE_PAUSED, STATE_STOPPED = 1, 2, 3     # MPNowPlayingPlaybackState
MEDIA_TYPE_VIDEO = 2                                     # MPNowPlayingInfoMediaTypeVideo
STATUS_SUCCESS, STATUS_FAILED = 0, 200                   # MPRemoteCommandHandlerStatus

# command -> what AniGUI does with it ("seek" gets the second you dragged to)
COMMANDS = (
    ("playCommand", "play"),
    ("pauseCommand", "pause"),
    ("togglePlayPauseCommand", "toggle"),
    ("nextTrackCommand", "next"),
    ("previousTrackCommand", "previous"),
    ("changePlaybackPositionCommand", "seek"),
)

_BLOCK_IS_GLOBAL = 1 << 28
_HANDLER = CFUNCTYPE(c_long, c_void_p, c_void_p)           # ^MPRemoteCommandHandlerStatus(event)


class _Size(Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


_ARTWORK = CFUNCTYPE(c_void_p, c_void_p, _Size)           # ^NSImage *(CGSize size)


class _Descriptor(Structure):
    _fields_ = [("reserved", c_ulong), ("size", c_ulong)]


class _Block(Structure):
    _fields_ = [("isa", c_void_p), ("flags", c_int), ("reserved", c_int),
                ("invoke", c_void_p), ("descriptor", POINTER(_Descriptor))]


class NowPlaying:
    """start(on_command) once; then show(...) as playback changes, and clear() when it stops.
    on_command(name, value) is called on the main thread (value: seconds for "seek")."""

    def __init__(self) -> None:
        self.ok = False
        self.started = False
        self._keep: list = []            # blocks and callbacks macOS holds on to
        self._targets: list[tuple[int, int]] = []
        self._art: tuple[str, int, object] | None = None    # (path, NSImage, artwork)
        self._on_command: Callable[[str, float | None], None] | None = None
        if sys.platform != "darwin":
            return
        try:
            self._objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
            self._mp = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/MediaPlayer.framework/MediaPlayer")
            system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            self._global_block = ctypes.addressof(c_void_p.in_dll(system, "_NSConcreteGlobalBlock"))
            o = self._objc
            o.objc_getClass.restype = c_void_p
            o.objc_getClass.argtypes = [c_char_p]
            o.sel_registerName.restype = c_void_p
            o.sel_registerName.argtypes = [c_char_p]
            addr = ctypes.cast(o.objc_msgSend, c_void_p).value
            self._send = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(addr)
            self._send_ptr = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p)(addr)
            self._send_str = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_char_p)(addr)
            self._send_2ptr = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p)(addr)
            self._send_double = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_double)(addr)
            self._send_long = CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(addr)
            self._send_bool = CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(addr)
            self._get_double = CFUNCTYPE(c_double, c_void_p, c_void_p)(addr)
            self._art_init = CFUNCTYPE(c_void_p, c_void_p, c_void_p, _Size, c_void_p)(addr)
            self._class = {name: o.objc_getClass(name.encode()) for name in (
                "MPNowPlayingInfoCenter", "MPRemoteCommandCenter", "MPMediaItemArtwork", "NSMutableDictionary",
                "NSString", "NSNumber", "NSImage")}
            self._key = {name: c_void_p.in_dll(self._mp, name).value for name in (
                "MPMediaItemPropertyTitle", "MPMediaItemPropertyArtist", "MPMediaItemPropertyAlbumTitle",
                "MPMediaItemPropertyPlaybackDuration", "MPNowPlayingInfoPropertyElapsedPlaybackTime",
                "MPNowPlayingInfoPropertyPlaybackRate", "MPNowPlayingInfoPropertyMediaType",
                "MPMediaItemPropertyArtwork")}
            self.ok = all(self._class.values()) and all(self._key.values())
        except (OSError, AttributeError, ValueError):
            self.ok = False

    def _sel(self, name: str):
        return self._objc.sel_registerName(name.encode())

    def _string(self, text: str):
        return self._send_str(self._class["NSString"], self._sel("stringWithUTF8String:"), text.encode())

    def _number(self, value: float):
        return self._send_double(self._class["NSNumber"], self._sel("numberWithDouble:"), float(value))

    def _block(self, kind, fn) -> int:
        invoke = kind(fn)
        desc = _Descriptor(0, ctypes.sizeof(_Block))
        block = _Block(self._global_block, _BLOCK_IS_GLOBAL, 0, ctypes.cast(invoke, c_void_p).value,
                       ctypes.pointer(desc))
        self._keep += [invoke, desc, block]
        return ctypes.addressof(block)

    def _center(self):
        return self._send(self._class["MPNowPlayingInfoCenter"], self._sel("defaultCenter"))

    def _commands(self):
        return self._send(self._class["MPRemoteCommandCenter"], self._sel("sharedCommandCenter"))

    # -- the keys --------------------------------------------------------------------------------

    def start(self, on_command: Callable[[str, float | None], None]) -> bool:
        if not self.ok:
            return False
        self._on_command = on_command
        if self.started:
            return True
        center = self._commands()
        for selector, name in COMMANDS:
            command = self._send(center, self._sel(selector))
            if not command:
                continue

            def handler(_block, event, _name=name):
                try:
                    value = None
                    if _name == "seek" and event:
                        value = float(self._get_double(event, self._sel("positionTime")))
                    if self._on_command is not None:
                        self._on_command(_name, value)
                    return STATUS_SUCCESS
                except Exception:  # noqa: BLE001 (never let an error cross into macOS)
                    return STATUS_FAILED

            target = self._send_ptr(command, self._sel("addTargetWithHandler:"), self._block(_HANDLER, handler))
            self._send_bool(command, self._sel("setEnabled:"), True)
            self._targets.append((command, target))
        self.started = True
        return True

    def stop(self) -> None:
        """Hands the media keys back (to Music, or whatever played before)."""
        if not self.ok:
            return
        for command, target in self._targets:
            self._send_ptr(command, self._sel("removeTarget:"), target)
            self._send_bool(command, self._sel("setEnabled:"), False)
        self._targets = []
        self.started = False
        self.clear()

    # -- what's playing --------------------------------------------------------------------------

    def _artwork(self, path: str | None):
        if not path:
            return None
        if self._art and self._art[0] == path:
            return self._art[2]
        image = self._send_ptr(self._send(self._class["NSImage"], self._sel("alloc")),
                               self._sel("initWithContentsOfFile:"), self._string(path))
        if not image:
            return None

        def provide(_block, _size, _image=image):
            return _image

        art = self._art_init(self._send(self._class["MPMediaItemArtwork"], self._sel("alloc")),
                             self._sel("initWithBoundsSize:requestHandler:"), _Size(600, 900),
                             self._block(_ARTWORK, provide))
        if self._art:
            self._send(self._art[1], self._sel("release"))
            self._send(self._art[2], self._sel("release"))
        self._art = (path, image, art)
        return art

    def show(self, title: str, show: str, position: float, duration: float | None, playing: bool,
             poster: str | None = None) -> None:
        """title: "Episode 5"; show: the show's name; poster: a picture file on this Mac."""
        if not self.ok:
            return
        info = self._send(self._class["NSMutableDictionary"], self._sel("dictionary"))
        put = self._sel("setObject:forKey:")
        k = self._key
        self._send_2ptr(info, put, self._string(title), k["MPMediaItemPropertyTitle"])
        self._send_2ptr(info, put, self._string(show), k["MPMediaItemPropertyArtist"])
        self._send_2ptr(info, put, self._string(show), k["MPMediaItemPropertyAlbumTitle"])
        if duration:
            self._send_2ptr(info, put, self._number(duration), k["MPMediaItemPropertyPlaybackDuration"])
        self._send_2ptr(info, put, self._number(max(0.0, position)), k["MPNowPlayingInfoPropertyElapsedPlaybackTime"])
        self._send_2ptr(info, put, self._number(1.0 if playing else 0.0), k["MPNowPlayingInfoPropertyPlaybackRate"])
        self._send_2ptr(info, put, self._number(MEDIA_TYPE_VIDEO), k["MPNowPlayingInfoPropertyMediaType"])
        art = self._artwork(poster)
        if art:
            self._send_2ptr(info, put, art, k["MPMediaItemPropertyArtwork"])
        center = self._center()
        self._send_ptr(center, self._sel("setNowPlayingInfo:"), info)
        self._send_long(center, self._sel("setPlaybackState:"), STATE_PLAYING if playing else STATE_PAUSED)

    def clear(self) -> None:
        if not self.ok:
            return
        center = self._center()
        self._send_ptr(center, self._sel("setNowPlayingInfo:"), None)
        self._send_long(center, self._sel("setPlaybackState:"), STATE_STOPPED)
