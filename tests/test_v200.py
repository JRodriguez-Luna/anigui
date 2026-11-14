"""v2.0 stage 1: Cinema look, the Full bleed watch page, the pop-out player, staying awake."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core.power import KeepAwake  # noqa: E402
from test_step4 import STARFALL, fast, pump, win  # noqa: E402,F401
from test_v1110 import play_inside  # noqa: E402


class FakePower:
    def __init__(self):
        self.held, self.next_id = set(), 7

    def hold(self, reason):
        self.next_id += 1
        self.held.add(self.next_id)
        return self.next_id

    def let_go(self, ident):
        self.held.discard(ident)


def test_keep_awake_holds_once_and_lets_go():
    power = FakePower()
    k = KeepAwake(power)
    k.hold()
    k.hold()
    assert k.held and len(power.held) == 1
    k.release()
    k.release()
    assert not k.held and not power.held


def test_mac_stays_awake_only_while_playing(win):
    power = FakePower()
    win.player_host.awake = KeepAwake(power)
    mpv = play_inside(win)
    mpv.set_prop("pause", False)
    assert pump(lambda: win.player_host.awake.held)
    mpv.set_prop("pause", True)
    assert pump(lambda: not win.player_host.awake.held)
    mpv.set_prop("pause", False)
    assert pump(lambda: win.player_host.awake.held)
    win.player_host.close_player()
    assert pump(lambda: not win.player_host.awake.held and not power.held)


# -- the Full bleed watch page -------------------------------------------------------------------

def test_video_fits_the_window(win):
    play_inside(win)
    slot = win.detail.theater.slot
    slot.set_room(600)
    assert slot.heightForWidth(1600) == 600 - slot.RESERVE          # tall windows: capped so the title shows
    assert slot.heightForWidth(640) == 360                          # narrow: plain 16:9
    slot.set_room(100)
    assert slot.heightForWidth(1600) >= 220                         # never collapses


def test_back_lives_in_the_player(win):
    play_inside(win)
    assert pump(lambda: win.player_host.mode == "theater")
    win.player_host._action("back")
    assert pump(lambda: win.stack.currentWidget() is not win.detail)
    assert win.playback.session is not None and win.playback.session.alive   # keeps playing in the corner
    assert pump(lambda: win.player_host.mode == "mini")


def test_all_episodes_opens_the_drawer(win):
    play_inside(win)
    host = win.player_host
    assert pump(lambda: host.mode == "theater")
    assert not host.drawer.isVisible()
    win.detail.theater.all_btn.click()
    assert pump(lambda: host.drawer.isVisible())
    assert win.detail.theater.rail.parentWidget() is host.drawer
    host._action("list")
    assert pump(lambda: not host.drawer.isVisible())


def test_episode_strip_replaces_the_grid(win):
    play_inside(win)
    d = win.detail
    assert pump(lambda: d.theater.strip.model().rowCount() > 0)
    assert not d.episodes_box.isVisible()


def test_sticky_bar_takes_you_back_to_the_video(win):
    play_inside(win)
    d = win.detail
    win.resize(1100, 640)
    pump(lambda: False, 0.3)
    bar = d.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert pump(lambda: d.sticky.isVisible())
    assert d.sticky.play.text() == "⤒  Back to the video"
    assert d.sticky.where.text().startswith("▶ Playing episode 5")
    d.sticky.play.click()
    assert pump(lambda: bar.value() == 0)


# -- the Cinema look ---------------------------------------------------------------------------

def test_artwork_runs_under_the_sidebar(win):
    amb = win.ambient
    win.home.load_remote()
    assert pump(lambda: win.home.hero.items)
    assert amb.source is win.home.hero and amb.mode == "band"
    assert win.home.hero.ambient is amb                 # the hero only holds the words now
    band = amb.band_rect()
    assert band.left() == 0 and band.width() == amb.width()   # edge to edge, under the sidebar
    win.go(win.search)
    assert amb.source is None and amb.mode == "none" and win.home.hero.ambient is None


def test_show_page_backdrop_and_watching_glow(win):
    amb = win.ambient
    play_inside(win)
    assert pump(lambda: amb.source is win.detail.header and amb.mode == "glow")
    win.player_host.close_player()
    assert pump(lambda: amb.mode == "band" and amb.source is win.detail.header)
    url = "https://img.example/new-banner.jpg"
    seen = []
    amb.source_changed = lambda src: seen.append(src)      # the backdrop hears about new art
    win.detail.header.set_image(url)
    assert seen == [win.detail.header]


def test_scrolling_moves_the_artwork(win):
    amb = win.ambient
    win.home.load_remote()
    assert pump(lambda: win.home.hero.items)
    top = amb.band_rect().top()
    bar = win.home.verticalScrollBar()
    bar.setValue(min(200, bar.maximum()))
    assert pump(lambda: amb.band_rect().top() < top or bar.maximum() == 0)


# -- the pop-out player -------------------------------------------------------------------------

from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402


def pop(win):
    play_inside(win)
    host = win.player_host
    assert pump(lambda: host.mode == "theater")
    host._action("popout")
    assert pump(lambda: host.mode == "pop" and host.popout.isVisible())
    return host


def test_pop_out_floats_above_everything(win):
    host = pop(win)
    w = host.popout
    assert host.parentWidget() is w and host.video.parentWidget() is host
    assert w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert abs(w.height() - w.width() * 9 / 16) <= 1                 # 16:9
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert area.contains(w.geometry())
    assert win.detail.theater.slot.popped                             # the page says where it went
    assert win.playback.session.alive                                 # still the same episode


def test_drag_it_anywhere_but_not_off_screen(win):
    host = pop(win)
    w = host.popout
    start = w.geometry()
    host.controls.dragBy.emit(QPointF(-150, -90))
    assert w.geometry().topLeft() == start.topLeft() + QPoint(-150, -90)
    host.controls.dragBy.emit(QPointF(-100000, 100000))
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert area.contains(w.geometry())
    host._action("moved")
    g = w.geometry()
    assert win.ctx.pref("popout_rect") == [g.x(), g.y(), g.width()]


def test_resize_from_a_corner_stays_16_9(win):
    host = pop(win)
    w = host.popout
    w.setGeometry(QRect(100, 100, 480, 270))
    grip = [g for g in host.grips if g.corner == (1, 1)][0]
    assert grip.isVisible()
    grip._start = (QPointF(580, 370), w.geometry())

    class Move:
        def __init__(self, x, y):
            self.p = QPointF(x, y)

        def globalPosition(self):
            return self.p
    grip.mouseMoveEvent(Move(700, 370))
    assert pump(lambda: w.width() == 600)
    assert w.width() == 600 and w.height() == 338 and w.pos() == QPoint(100, 100)
    grip.mouseMoveEvent(Move(0, 0))
    assert pump(lambda: w.width() == 288)                                           # not smaller than this
    grip.mouseReleaseEvent(None)
    assert win.ctx.pref("popout_rect")[2] == 288


def test_bring_it_back(win):
    host = pop(win)
    win.detail.theater.slot.bringBack.emit()
    assert pump(lambda: host.mode == "theater" and not host.popout.isVisible())
    assert host.parentWidget() is win.detail.theater.slot            # back in the page
    assert not win.detail.theater.slot.popped
    assert win.playback.session.alive


def test_back_to_anigui_button_opens_the_show(win):
    host = pop(win)
    win.go(win.home)
    host._action("popin")
    assert pump(lambda: win.stack.currentWidget() is win.detail and host.mode == "theater")


def test_closing_the_pop_out_stops_the_player(win):
    host = pop(win)
    host.popout.close()                                # ⌘W on the floating window
    assert pump(lambda: not host.active and not host.popout.isVisible(), 8)
    assert host.parentWidget() is not host.popout


def test_remembers_where_you_put_it(win):
    host = pop(win)
    host.popout.setGeometry(QRect(140, 120, 400, 225))
    host._action("popin")
    assert pump(lambda: host.mode == "theater")
    host._action("popout")
    assert pump(lambda: host.mode == "pop")
    assert host.popout.geometry() == QRect(140, 120, 400, 225)


def test_switching_to_dub_stays_popped_out(win):
    host = pop(win)
    t = win.detail.theater
    t.audio.setCurrentIndex(t.audio.findData(True))
    assert pump(lambda: host.active and host.mode == "pop" and host.popout.isVisible(), 8)


def test_dropped_off_screen_slides_back(win):
    host = pop(win)
    w = host.popout
    w.move(-5000, -5000)
    assert pump(lambda: QGuiApplication.primaryScreen().availableGeometry().contains(w.geometry()), 3)
    g = w.geometry()
    assert win.ctx.pref("popout_rect") == [g.x(), g.y(), g.width()]


def test_backdrop_is_drawn_once_and_reused(win):
    amb = win.ambient
    win.go(win.search)
    first = amb._layer_for(amb.width(), amb.height())
    assert amb._layer_for(amb.width(), amb.height()) is first


def test_snow_repaints_only_where_flakes_move(win):
    from ui.holiday import SnowLayer
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    snow = SnowLayer(host, flakes=36)
    snow.start()
    areas = []
    snow.update = lambda region=None, *a: areas.append(sum(r.width() * r.height() for r in region))
    snow._step()
    assert areas and areas[0] < 1200 * 800 * 0.05     # a few dozen flakes, not the whole page
    host.close()


def test_video_is_part_of_the_page_while_watching(win):
    play_inside(win)
    host = win.player_host
    assert pump(lambda: host.mode == "theater")
    slot = win.detail.theater.slot
    assert host.parentWidget() is slot and host.geometry() == slot.rect()   # scrolls with the page
    sb = win.detail.verticalScrollBar()
    sb.setValue(sb.maximum())
    assert pump(lambda: host.mode == "mini" and host.parentWidget() is win.centralWidget())
    sb.setValue(0)
    assert pump(lambda: host.mode == "theater" and host.parentWidget() is slot)


def test_popping_out_doesnt_scroll_the_page(win):
    host = pop(win)
    assert win.detail.verticalScrollBar().value() == 0
    host._action("popin")
    assert pump(lambda: host.mode == "theater")
    assert win.detail.verticalScrollBar().value() == 0


def test_sticky_bar_has_its_own_strip(win):
    play_inside(win)
    d = win.detail
    win.resize(1100, 640)
    pump(lambda: False, 0.3)
    sb = d.verticalScrollBar()
    sb.setValue(sb.maximum())
    assert pump(lambda: d.sticky.isVisible() and d._bar_room)
    assert d.viewportMargins().top() == d.sticky.height()                   # not over the page
    assert d.sticky.geometry().bottom() < d.viewport().geometry().top()


# -- smoother scrolling ------------------------------------------------------------------------

def test_cards_are_drawn_once_then_copied(win):
    from ui.paintcache import CARDS
    win.home.load_remote()
    row = win.home.trending_row
    assert pump(lambda: row.model().cards())
    vp = row.view.viewport()

    def settled():                                             # covers arrived and finished fading in:
        vp.repaint()                                           # a repaint draws nothing new (a slow
        misses = CARDS.misses                                  # cover on a busy CI Mac used to count)
        vp.repaint()
        return CARDS.misses == misses
    assert pump(settled, 8)
    before = (CARDS.hits, CARDS.misses)
    vp.repaint()
    assert CARDS.hits > before[0] and CARDS.misses == before[1]   # copied, not drawn again


def test_pages_paint_their_own_backdrop(win):
    body = win.home.widget()
    assert win.ambient.page_body is body
    assert body.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)   # so scrolling can reuse it
    win.go(win.stats)
    assert win.ambient.page_body is win.stats.widget()


def test_decorations_hold_still_while_scrolling(win):
    from ui import motion
    from ui.holiday import SnowLayer
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    host.resize(400, 300)
    host.show()
    snow = SnowLayer(host, flakes=10)
    snow.start()
    snow._step()
    where = [list(f) for f in snow.flakes]
    motion.note_scroll()
    snow._step()
    assert [list(f) for f in snow.flakes] == where             # paused
    motion._last_scroll = 0.0
    snow._step()
    assert [list(f) for f in snow.flakes] != where
    host.close()


def test_frame_rate_readout(win):
    m = win.frame_meter
    assert m.isHidden()
    m.toggle()
    assert pump(lambda: m.fps > 0, 3)
    assert "fps" in m.text() and "slowest frame" in m.text()
    m.toggle()
    assert m.isHidden() and not m._tick.isActive()


def test_mpv_never_holds_the_main_thread():
    """Rendering must not wait for the frame's display time (it made the app 26 fps while playing)."""
    import inspect
    from core import libmpv
    assert libmpv.RENDER_BLOCK_FOR_TARGET_TIME == 12
    src = inspect.getsource(libmpv.GlRenderer.render)
    assert "RENDER_BLOCK_FOR_TARGET_TIME" in src and "c_int(0)" in src


def test_episode_list_closes(win):
    play_inside(win)
    host = win.player_host
    t = win.detail.theater
    assert pump(lambda: host.mode == "theater")
    t.all_btn.click()
    assert pump(lambda: host.drawer.isVisible()) and t.all_btn.text() == "✕  Hide episodes"
    t.all_btn.click()                                              # the same button closes it
    assert pump(lambda: not host.drawer.isVisible()) and t.all_btn.text() == "☰  All episodes"
    t.all_btn.click()
    host.drawer_close.click()                                      # its ✕
    assert pump(lambda: not host.drawer.isVisible())
    t.all_btn.click()
    win._escape()                                                  # Esc closes it (and stays on the page)
    assert pump(lambda: not host.drawer.isVisible()) and win.stack.currentWidget() is win.detail
    t.all_btn.click()
    host._action("play")                                           # a click on the video beside it
    assert pump(lambda: not host.drawer.isVisible())
