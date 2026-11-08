"""Shared services handed to every page."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QSettings, Signal

from core.catalog import Catalog
from core.covers import CoverCache
from core.store import Store
from core.tasks import TaskRunner

from .images import ImageLoader


# Every user preference, with its default. Settings, pages and playback all read these.
DEFAULTS: dict[str, Any] = {
    "player": "auto",            # auto | iina | mpv
    "dub": False,
    "quality": "best",           # best | 1080 | 720 | 480
    "autoplay": True,
    "player_lights": True,       # holiday theme: lights and garland around the built-in player
    "player_snow": True,
    "player_bow": True,
    "skip_intro": False,
    "skip_ending": False,
    "skip_recap": False,
    "skip_fillers": False,       # Up Next and auto-play jump over filler / recap episodes
    "hide_fillers": False,       # leave them out of the episode grid
    "dub_subtitles": False,      # show the (Japanese-timed) subtitles over dubbed audio
    "lock_app": False,           # Touch ID to open AniGUI (2.0)
    "lock_mature": False,        # Touch ID before 18+ shows (2.0)
    "hide_mature": True,         # keep 18+ shows out of suggestions; blur and ask for your own
    "alerts": True,              # look for new episodes
    "alerts_scope": "library",   # library | library+continue
    "notify": True,              # Mac notifications for new episodes
    "import_history": False,     # bring in shows watched with ani-cli in Terminal (asked in Setup)
    "check_updates": True,
    "accent": "ember",           # Make it yours (2.0): ember | sakura | ocean | matcha | violet | gold
    "app_icon": "classic",       # classic | accent (tinted to your accent)
    "your_name": "",             # for Home's greeting (empty: no greeting)
    "home_rows": "",             # Home's rows, in your order: "key:1,key:0,…" ("" = the usual)
    "holiday_theme": "auto",     # auto (day after Thanksgiving to Jan 1) | early (from Nov 1) | off
    "holiday_banner_seen": "",   # the year November's "holiday theme is ready" banner was answered
}


class PrefEvents(QObject):
    changed = Signal(str, object)   # key, new value


@dataclass
class AppContext:
    store: Store
    catalog: Catalog
    runner: TaskRunner      # data calls (network, SQLite)
    images: ImageLoader
    bridge: Any             # core.cli_bridge.CliBridge (or a test double)
    player: Any             # core.player.Player (or a test double)
    settings: QSettings
    events: PrefEvents = field(default_factory=PrefEvents)
    stills: Any = None      # core.stills.EpisodeStills; None = numbered tiles only
    fillers: Any = None     # core.fillers.FillerGuide; None = no filler info

    @classmethod
    def create(cls) -> "AppContext":
        from core.cli_bridge import CliBridge
        from core.player import Player

        from core.fillers import FillerGuide
        from core.stills import EpisodeStills

        store = Store()
        catalog = Catalog(store)
        return cls(
            store=store,
            catalog=catalog,
            runner=TaskRunner(),
            images=ImageLoader(CoverCache()),
            bridge=CliBridge(),
            player=Player(),
            settings=QSettings("AniGUI", "AniGUI"),
            stills=EpisodeStills(catalog.anilist, store),
            fillers=FillerGuide(store),
        )

    # Preferences (QSettings). `default` falls back to DEFAULTS for known keys.
    _MISSING = object()

    def pref(self, key: str, default: Any = _MISSING) -> Any:
        if default is AppContext._MISSING:
            default = DEFAULTS.get(key)
        value = self.settings.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        return value

    def set_pref(self, key: str, value: Any) -> None:
        if self.settings.value(key) == value:
            return
        self.settings.setValue(key, value)
        self.events.changed.emit(key, value)

    def shutdown(self) -> None:
        self.runner.pool.clear()
        self.images.runner.pool.clear()
        self.runner.wait(1500)
        self.images.runner.wait(500)
        self.store.close()
