"""How hard the Mac works for a player (2.0.1): CPU time used by a process, which processes
are a given app, and whether the Mac is running on battery. All read on this Mac, nothing is
sent anywhere."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import resource
import subprocess
import sys


def own_cpu_seconds() -> float:
    """CPU time used by AniGUI so far (every thread: the window, the built-in player, mpv)."""
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def parse_cputime(text: str) -> float | None:
    """ps's TIME column: "1:02.50", "0:00.07", "1:02:03.40" or "2-01:02:03"."""
    text = text.strip()
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    days, hours, minutes, seconds = m.groups()
    total = float(seconds) + int(minutes) * 60
    if hours:
        total += int(hours) * 3600
    if days:
        total += int(days) * 86400
    return total


def cpu_seconds(pid: int) -> float | None:
    """CPU time another process has used so far, or None if it's gone."""
    if pid == os.getpid():
        return own_cpu_seconds()
    try:
        out = subprocess.run(["ps", "-o", "time=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_cputime(out.stdout) if out.returncode == 0 else None


def pids_named(name: str) -> set[int]:
    """Running processes with exactly this name (e.g. "IINA")."""
    try:
        out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(x) for x in out.stdout.split() if x.isdigit()}


def percent(cpu_before: float, cpu_after: float, seconds: float) -> float:
    """CPU use over a stretch of time, as % of one processor core (what Activity Monitor shows)."""
    if seconds <= 0:
        return 0.0
    return max(0.0, (cpu_after - cpu_before) / seconds * 100)


# -- battery ---------------------------------------------------------------------------------------

def on_battery() -> bool:
    """True when this Mac is running on its battery (not plugged in). False elsewhere."""
    if sys.platform != "darwin":
        return False
    try:
        iokit = ctypes.CDLL(ctypes.util.find_library("IOKit") or "/System/Library/Frameworks/IOKit.framework/IOKit")
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation")
                         or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        iokit.IOPSCopyPowerSourcesInfo.restype = ctypes.c_void_p
        iokit.IOPSGetProvidingPowerSourceType.restype = ctypes.c_void_p
        iokit.IOPSGetProvidingPowerSourceType.argtypes = [ctypes.c_void_p]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        info = iokit.IOPSCopyPowerSourcesInfo()
        if not info:
            return False
        try:
            kind = iokit.IOPSGetProvidingPowerSourceType(info)      # not owned: don't release
            buf = ctypes.create_string_buffer(64)
            if not kind or not cf.CFStringGetCString(kind, buf, 64, 0x08000100):
                return False
            return buf.value.decode() == "Battery Power"
        finally:
            cf.CFRelease(info)
    except (OSError, AttributeError):
        return False
