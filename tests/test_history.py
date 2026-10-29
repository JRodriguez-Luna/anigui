"""v1.1.1: clearing watch history (all of it, or one show) and keeping it cleared."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import ui_fakes  # noqa: E402
from core import paths  # noqa: E402
from core.store import Store  # noqa: E402

HISTORY = (
    "3\tfrieren-beyond-journeys-end-18542\tFrieren: Beyond Journey's End\n"
    "12\tone-piece-100\tOne Piece\n"
)


@pytest.fixture
def hist(tmp_path, monkeypatch):
    path = tmp_path / "ani-hsts"
    path.write_text(HISTORY, encoding="utf-8")
    monkeypatch.setattr(paths, "ani_cli_history_file", lambda: path)
    return path


def test_clear_history_keeps_my_list_and_stays_cleared(tmp_path, hist):
    store = Store(tmp_path / "t.db")
    assert store.import_ani_cli_history() == 2
    store.upsert_show("bocchi-1", "Bocchi")
    store.record_progress("bocchi-1", "5", 300, 1400)
    store.set_in_library("bocchi-1", True)

    assert store.clear_history() == 3
    assert store.continue_watching() == []
    assert store.get_progress("bocchi-1", "5") is None
    assert [s.anime_id for s in store.library()] == ["bocchi-1"]

    # ani-cli's file is untouched, but its entries don't come back on the next launch
    assert hist.read_text(encoding="utf-8") == HISTORY
    assert store.import_ani_cli_history() == 0
    assert store.continue_watching() == []

    # Watching a new episode in Terminal ani-cli later does show up again
    hist.write_text(HISTORY.replace("12\tone-piece-100", "13\tone-piece-100"), encoding="utf-8")
    assert store.import_ani_cli_history() == 1
    assert [(i.show.anime_id, i.last.episode) for i in store.continue_watching()] == [("one-piece-100", "13")]


def test_remove_one_show(tmp_path, hist):
    store = Store(tmp_path / "t.db")
    store.import_ani_cli_history()
    store.forget_show_progress("one-piece-100")
    assert [i.show.anime_id for i in store.continue_watching()] == ["frieren-beyond-journeys-end-18542"]
    assert store.import_ani_cli_history() == 0
    assert [i.show.anime_id for i in store.continue_watching()] == ["frieren-beyond-journeys-end-18542"]


def test_upgrades_v1_database(tmp_path):
    db = tmp_path / "old.db"
    Store(db).close()
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE history_hidden")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    store = Store(db)
    assert store.clear_history(tmp_path / "missing") == 0
    assert store._conn().execute("PRAGMA user_version").fetchone()[0] == 2


def _pump(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _answer_dialog(button_text: str) -> None:
    def click():
        box = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()), None)
        if box is None:
            QTimer.singleShot(20, click)
            return
        assert "My List stays" in box.informativeText()
        next(b for b in box.buttons() if b.text() == button_text).click()
    QTimer.singleShot(20, click)


def test_home_clear_button(tmp_path, hist):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path)
    win = MainWindow(ctx)
    win.show()
    win.home.refresh_local()
    row = win.home.continue_row
    assert row.isVisible() and row.model().rowCount() == 3 and win.home.clear_btn.isVisible()

    _answer_dialog("Cancel")
    win.home.clear_btn.click()
    assert row.model().rowCount() == 3

    _answer_dialog("Clear History")
    win.home.clear_btn.click()
    assert _pump(lambda: not row.isVisible())
    assert ctx.store.continue_watching() == []
    assert win.home.library_row.model().rowCount() == 2  # My List kept
    win.close()
    ctx.shutdown()


def test_home_right_click_remove(tmp_path, hist):
    from ui.main_window import MainWindow

    ctx = ui_fakes.fake_context(tmp_path)
    win = MainWindow(ctx)
    win.show()
    win.home.refresh_local()
    row = win.home.continue_row
    from ui.cards import CARD_ROLE
    first = row.model().index(0, 0).data(CARD_ROLE)

    def pick_remove():
        menu = QApplication.activePopupWidget()
        if menu is None:
            QTimer.singleShot(20, pick_remove)
            return
        menu.setActiveAction(menu.actions()[0])
        menu.actions()[0].trigger()
        menu.close()
    QTimer.singleShot(20, pick_remove)
    row.cardMenuRequested.emit(first, QPoint(200, 200))
    assert _pump(lambda: row.model().rowCount() == 2)
    assert first.payload.anime_id not in [i.show.anime_id for i in ctx.store.continue_watching()]
    win.close()
    ctx.shutdown()
