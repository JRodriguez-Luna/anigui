"""Shared services handed to every page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSettings

from core.catalog import Catalog
from core.covers import CoverCache
from core.store import Store
from core.tasks import TaskRunner

from .images import ImageLoader


@dataclass
class AppContext:
    store: Store
    catalog: Catalog
    runner: TaskRunner      # data calls (network, SQLite)
    images: ImageLoader
    bridge: Any             # core.cli_bridge.CliBridge (or a test double)
    player: Any             # core.player.Player (or a test double)
    settings: QSettings

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

    # Playback preferences
    def pref(self, key: str, default: Any) -> Any:
        value = self.settings.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        return value

    def set_pref(self, key: str, value: Any) -> None:
        self.settings.setValue(key, value)

    def shutdown(self) -> None:
        self.runner.pool.clear()
        self.images.runner.pool.clear()
        self.runner.wait(1500)
        self.images.runner.wait(500)
        self.store.close()
