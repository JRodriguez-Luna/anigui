"""2.0 stage 3: the personal features."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_step4 import STARFALL, pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


def open_starfall(w):
    w.open_item(w.ctx.store.get_show(STARFALL))
    assert pump(lambda: w.detail.grid.model_.items)


# -- sleep timer ---------------------------------------------------------------------------------

def test_sleep_timer_fades_out_and_pauses(win):
    mpv = play_inside(win)
    host = win.player_host
    host.set_sleep(15)
    assert host.controls.sleep_text == "15 min" and host._sleep_tick.isActive()
    host.sleep_at = 0                               # time's up
    host._sleep_check()
    assert pump(lambda: any(c[:3] == ["set_property", "pause", True] for c in mpv.commands), 8)
    assert host.controls.sleep_text == "" and host.sleep_at is None


def test_sleep_at_the_end_of_the_episode(win):
    mpv = play_inside(win)
    host = win.player_host
    host.set_sleep("episode")
    assert host.sleep_after_episode and host.controls.sleep_text == "end of episode"
    host._on_countdown("Episode 6", 10)              # instead of the next one…
    assert pump(lambda: any(c[:3] == ["set_property", "pause", True] for c in mpv.commands), 8)
    assert not host.sleep_after_episode


# -- not interested ------------------------------------------------------------------------------

def test_not_interested_leaves_suggestions(win):
    win.home.load_remote()
    row = win.home.trending_row
    assert pump(lambda: row.model().cards() and row.model().cards()[0].payload is not None)
    media = row.model().cards()[0].payload
    win.home.not_interested(media)
    assert media.anilist_id not in [c.payload.anilist_id for c in row.model().cards() if c.payload]
    assert win.ctx.store.not_interested() == [(media.anilist_id, media.display_title)]
    win.ctx.store.set_not_interested(media.anilist_id, media.display_title, False)
    win.home.apply_content_filter()
    assert media.anilist_id in [c.payload.anilist_id for c in row.model().cards() if c.payload]


# -- spoiler shield ------------------------------------------------------------------------------

def test_spoiler_shield(win):
    win.ctx.set_pref("spoiler_shield", True)
    open_starfall(win)
    items = {i.number: i for i in win.detail.grid.model_.items}
    nxt = win.detail.play_target
    assert not items[nxt].shield                                   # the one you're on shows
    later = [i for n, i in items.items() if i.state == "new" and n != nxt]
    assert later and all(i.shield and i.title is None for i in later)
    assert all(not i.shield for i in items.values() if i.state == "watched")
    win.ctx.set_pref("spoiler_shield", False)
    assert pump(lambda: not any(i.shield for i in win.detail.grid.model_.items))


# -- rewatch mode --------------------------------------------------------------------------------

def test_rewatch_from_an_episode(win):
    s = win.ctx.store
    open_starfall(win)
    d = win.detail
    d._mark("2", "rewatch")
    assert s.rewatch(STARFALL) == ("2", 1)
    assert d.play_target == "2" and d.play_btn.text().startswith("↺  Rewatch Episode 2")
    assert d.rewatch_btn.isVisible()
    s.record_progress(STARFALL, "2", 1400, 1420)
    d._on_progress(STARFALL, "2")
    assert s.rewatch(STARFALL) == ("3", 1)
    d._stop_rewatch()
    assert s.rewatch(STARFALL) is None and not d.rewatch_btn.isVisible()
    assert s.start_rewatch(STARFALL, "1") == 2                     # the second time round
    assert any(m.kind == "rewatch" for m in s.timeline())
