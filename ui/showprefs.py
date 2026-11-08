"""Per-show settings and subtitle style (2.0).

A show remembers your Sub/Dub and quality choice on its page, and can have its own intro and
ending skipping and subtitle size. Anything not set for a show uses your usual setting.
"""

from __future__ import annotations

SUB_SIZES = (("small", "Small", 0.8), ("normal", "Normal", 1.0), ("large", "Large", 1.25), ("huge", "Huge", 1.55))
SUB_COLORS = (("white", "White", "#FFFFFF"), ("yellow", "Yellow", "#FFE45C"))


def show_pref(ctx, anime_id: str | None, key: str):
    settings = ctx.store.show_settings(anime_id) if anime_id else {}
    return settings[key] if key in settings else ctx.pref(key)


def sub_style(ctx, anime_id: str | None) -> list[tuple[str, object]]:
    """mpv properties for your subtitle style (sent once a video has loaded)."""
    size = str(show_pref(ctx, anime_id, "sub_size") or "normal")
    scale = next((v for k, _n, v in SUB_SIZES if k == size), 1.0)
    color = next((v for k, _n, v in SUB_COLORS if k == str(ctx.pref("sub_color"))), "#FFFFFF")
    props: list[tuple[str, object]] = [("sub-scale", scale), ("sub-color", color)]
    if ctx.pref("sub_box"):
        props += [("sub-border-style", "opaque-box"), ("sub-back-color", "#B0000000"), ("sub-shadow-offset", 0)]
    return props
