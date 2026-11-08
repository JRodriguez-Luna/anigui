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


# -- moments -------------------------------------------------------------------------------------

def test_save_a_moment_and_go_back_to_it(win):
    mpv = play_inside(win)
    host = win.player_host
    host.controls.position = 754.0
    mid = host.save_moment()
    assert mid and pump(lambda: any(c[0] == "screenshot-to-file" and c[2] == "video" for c in mpv.commands))
    m = win.ctx.store.moments()[0]
    assert (m.anime_id, m.episode, int(m.position)) == (STARFALL, "5", 754) and m.image.endswith(".jpg")
    win.open_library(None)
    win.library.set_tab("moments")
    assert win.library.stack.currentWidget() is win.library.moments and win.library.moments.model_.rowCount() == 1
    played = []
    win.playback.play = lambda aid, title, ep, player=None, start=None: played.append((aid, ep, start))
    win.play_moment(m)
    assert played == [(STARFALL, "5", 752.0)]


# -- your queue ----------------------------------------------------------------------------------

def test_queue_on_home_and_after_the_last_episode(win):
    s = win.ctx.store
    shows = [r["anime_id"] for r in s._conn().execute("SELECT anime_id FROM shows WHERE anime_id != ? LIMIT 2", (STARFALL,))]
    s.enqueue(shows[0], "1")
    s.enqueue(shows[1], "3")
    s.move_in_queue(shows[1], 0)
    assert [a.anime_id for a, _e in s.queue()] == [shows[1], shows[0]]
    win.home.refresh_local()
    assert win.home.queue_row.model().rowCount() == 2
    assert win.home.queue_row.model().cards()[0].subtitle == "Up next: episode 3"
    # after a show's last episode, auto-play turns to your queue
    from ui.playback import Session
    sess = Session.__new__(Session)
    sess.ctx = win.ctx
    sess.episodes = ["1", "2"]

    class Now:
        anime_id, title, episode = STARFALL, "Starfall Academy", "2"
    sess.now = Now()
    sess.next_season = None
    sess.filler_keys = set()
    t = sess._next_target()
    assert (t.anime_id, t.episode) == (shows[1], "3") and t.label.startswith("From your queue")


# -- per-show settings ---------------------------------------------------------------------------

def test_a_show_remembers_sub_or_dub(win):
    from ui.showprefs import show_pref, sub_style
    open_starfall(win)
    d = win.detail
    d.dub_btn.click()
    assert win.ctx.store.show_settings(STARFALL)["dub"] is True
    win.ctx.set_pref("dub", False)                       # your usual changes…
    assert show_pref(win.ctx, STARFALL, "dub") is True   # …this show keeps its own
    assert d.dub_btn.isChecked()
    win.ctx.store.set_show_setting(STARFALL, "sub_size", "huge")
    win.ctx.set_pref("sub_box", True)
    props = dict(sub_style(win.ctx, STARFALL))
    assert props["sub-scale"] == 1.55 and props["sub-border-style"] == "opaque-box"
    d._reset_show_settings()
    assert win.ctx.store.show_settings(STARFALL) == {}
    win.ctx.set_pref("sub_box", False)


def test_subtitle_style_reaches_the_player(win):
    win.ctx.set_pref("sub_size", "large")
    mpv = play_inside(win)
    mpv.send_event("file-loaded")
    assert pump(lambda: ["set_property", "sub-scale", 1.25] in mpv.commands)
    win.ctx.set_pref("sub_size", "normal")


# -- goals ---------------------------------------------------------------------------------------

def test_weekly_goal_and_streak(win):
    import datetime as dt
    from core import goals
    s = win.ctx.store
    today = dt.date.today()
    for d in range(3):
        s.log_watch(STARFALL, str(10 + d), 1300, today - dt.timedelta(days=d))
    assert goals.streak(s) == 3
    assert goals.goal_line(2, 5, 3) == "2 of 5 episodes this week · 3-day streak"
    assert goals.goal_line(5, 5, 0) == "Goal met this week 🎉"
    win.ctx.set_pref("weekly_goal", 1)
    s.record_progress(STARFALL, "20", 1400, 1420)
    win._check_goal()
    assert win.ctx.pref("goal_met_week") == goals.week_start().isoformat()
    win.stats.refresh_goal()
    assert win.stats.goal_ring.goal == 1 and win.stats.goal_btn.text() == "Change goal"
    win.ctx.set_pref("weekly_goal", 0)
