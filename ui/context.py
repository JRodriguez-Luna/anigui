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
    "skip_intro": False,
    "skip_ending": False,
    "skip_recap": False,
    "alerts": True,              # look for new episodes
    "alerts_scope": "library",   # library | library+continue
    "notify": True,              # Mac notifications for new episodes
    "import_history": False,     # bring in shows watched with ani-cli in Terminal (asked in Setup)
    "check_updates": True,
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

    @classmethod
    def create(cls) -> "AppContext":
        from core.cli_bridge import CliBridge
        from core.player import Player

        store = Store()
        return cls(
            store=store,
            catalog=Catalog(store),
            runner=TaskRunner(),
            images=ImageLoader(CoverCache()),
            bridge=CliBridge(),
            player=Player(),
            settings=QSettings("AniGUI", "AniGUI"),
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
