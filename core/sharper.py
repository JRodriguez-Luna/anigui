"""Sharper picture (2.0): Anime4K's upscaling shaders (MIT, by bloc97), bundled in the app and
run by the built-in player on your Mac's graphics chip. Nothing is downloaded or sent anywhere.

Mode A (Fast) from Anime4K's own guide: tuned for 1080p and lower anime on Mac GPUs.
"""

from __future__ import annotations

import sys
from pathlib import Path

SHADERS = (
    "Anime4K_Clamp_Highlights.glsl",
    "Anime4K_Restore_CNN_M.glsl",
    "Anime4K_Upscale_CNN_x2_M.glsl",
    "Anime4K_AutoDownscalePre_x2.glsl",
    "Anime4K_AutoDownscalePre_x4.glsl",
    "Anime4K_Upscale_CNN_x2_S.glsl",
)


def folder() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / "anime4k"


def available() -> bool:
    return all((folder() / name).is_file() for name in SHADERS)


def shaders_value(on: bool) -> str:
    """The value for mpv's glsl-shaders ("" switches them off)."""
    if not on or not available():
        return ""
    return ":".join(str(folder() / name) for name in SHADERS)
