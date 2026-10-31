"""Stats: time watched, episodes, streaks, a 12-week chart, top genres and shows."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QToolTip, QVBoxLayout, QWidget,
)

from core import stats as core_stats
from core.stats import Stats, hours_text

from . import theme
from .cards import Card, CardRow
from .context import AppContext


class StatTile(QFrame):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent, objectName="StatTile")
        self.value = QLabel("–", objectName="StatValue")
        self.label = QLabel(label, objectName="StatLabel")
        self.note = QLabel("", objectName="StatNote", wordWrap=True)
        col = QVBoxLayout(self)
        col.setContentsMargins(18, 16, 18, 16)
        col.setSpacing(2)
        col.addWidget(self.label)
        col.addWidget(self.value)
        col.addWidget(self.note)
        col.addStretch(1)

    def set(self, value: str, note: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))


class WeeklyChart(QWidget):
    """Hours watched per week. One series, so one color, no legend; hover for exact values."""

    BAR_GAP = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.weeks: list = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str]] = []
        self._hover = -1

    def set_weeks(self, weeks) -> None:
        self.weeks = list(weeks)
        self.update()

    @staticmethod
    def _nice_max(hours: float) -> float:
        """Top of the y-axis: two gridlines above zero at round values."""
        for step in (0.5, 1, 2, 5, 10, 20, 50, 100):
            if hours <= step * 2:
                return step * 2
        return hours

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, top, bottom = 44, 8, 10, 26
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        hours = [s / 3600 for _d, s in self.weeks] or [0]
        ymax = self._nice_max(max(max(hours), 0.5))

        # Recessive grid and y labels
        small = theme.font(11)
        p.setFont(small)
        for k in range(3):
            v = ymax * k / 2
            y = plot.bottom() - plot.height() * k / 2
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(theme.FAINT))
            label = f"{v:g}h"
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        n = max(1, len(self.weeks))
        slot = plot.width() / n
        bar_w = min(34.0, slot * 0.62)
        self._bars = []
        for i, ((monday, seconds), h) in enumerate(zip(self.weeks, hours)):
            x = plot.left() + slot * i + (slot - bar_w) / 2
            height = plot.height() * (h / ymax) if ymax else 0
            rect = QRectF(x, plot.bottom() - height, bar_w, height)
            tip = f"Week of {monday:%b} {monday.day}: {hours_text(seconds)}"
            self._bars.append((QRectF(plot.left() + slot * i, plot.top(), slot, plot.height()), tip))
            if height > 0.5:
                path = QPainterPath()
                r = min(4.0, height / 2, bar_w / 2)  # rounded data end, square on the baseline
                path.moveTo(rect.left(), rect.bottom())
                path.lineTo(rect.left(), rect.top() + r)
                path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
                path.lineTo(rect.right() - r, rect.top())
                path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
                path.lineTo(rect.right(), rect.bottom())
                path.closeSubpath()
                color = QColor(theme.ACCENT_HOVER if i == self._hover else theme.ACCENT)
                p.fillPath(path, color)
            # x labels every 3 weeks, plus the current one
            if i % 3 == (n - 1) % 3:
                p.setPen(QColor(theme.MUTED if i == n - 1 else theme.FAINT))
                text = "This week" if i == n - 1 else f"{monday:%b} {monday.day}"
                p.drawText(QRectF(plot.left() + slot * i - 30, plot.bottom() + 6, slot + 60, 16),
                           Qt.AlignmentFlag.AlignHCenter, text)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        hit = next((i for i, (area, _t) in enumerate(self._bars) if area.contains(pos)), -1)
        if hit != self._hover:
            self._hover = hit
            self.update()
        if hit >= 0:
            QToolTip.showText(event.globalPosition().toPoint(), self._bars[hit][1], self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self.update()


class GenreBars(QWidget):
    """Top genres as horizontal bars: length is the episode count (one hue)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[tuple[str, int]] = []

    def set_rows(self, rows) -> None:
        self.rows = list(rows)
        self.setFixedHeight(max(1, len(self.rows)) * 30)
        self.update()

    def paintEvent(self, _event) -> None:
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(v for _g, v in self.rows) or 1
        label_w, value_w = 120, 64
        track = self.width() - label_w - value_w
        for i, (genre, count) in enumerate(self.rows):
            y = i * 30
            p.setFont(theme.font(13, QFont.Weight.DemiBold))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, label_w - 10, 22), Qt.AlignmentFlag.AlignVCenter, genre)
            w = max(3.0, track * count / top)
            path = QPainterPath()
            path.addRoundedRect(QRectF(label_w, y + 6, w, 10), 4, 4)
            p.fillPath(path, QColor(theme.ACCENT))
            p.setFont(theme.font(12))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(label_w + w + 8, y, value_w, 22), Qt.AlignmentFlag.AlignVCenter,
                       f"{count} ep{'s' if count != 1 else ''}")
        p.end()


class StatsPage(QScrollArea):
    openItem = Signal(object)  # Show

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stats: Stats | None = None

        title = QLabel("Your Stats", objectName="SectionTitle")
        self.subtitle = QLabel("", objectName="Muted", wordWrap=True)
        self.empty = QLabel("Nothing yet. Watch an episode and your stats start here.", objectName="EmptyState")

        self.time = StatTile("Time watched")
        self.episodes = StatTile("Episodes finished")
        self.started = StatTile("Shows started")
        self.finished = StatTile("Shows finished")
        self.streak = StatTile("Day streak")
        tiles = QGridLayout()
        tiles.setSpacing(12)
        for i, tile in enumerate((self.time, self.episodes, self.started, self.finished, self.streak)):
            tiles.addWidget(tile, 0, i)

        self.week = QLabel("", objectName="Muted")
        self.chart = WeeklyChart()
        chart_box = QFrame(objectName="StatPanel")
        cb = QVBoxLayout(chart_box)
        cb.setContentsMargins(18, 16, 18, 14)
        cb.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("Last 12 weeks", objectName="PanelTitle"))
        head.addStretch(1)
        head.addWidget(self.week)
        cb.addLayout(head)
        cb.addWidget(self.chart)

        self.genres = GenreBars()
        genre_box = QFrame(objectName="StatPanel")
        gb = QVBoxLayout(genre_box)
        gb.setContentsMargins(18, 16, 18, 16)
        gb.setSpacing(12)
        gb.addWidget(QLabel("Top genres", objectName="PanelTitle"))
        gb.addWidget(self.genres)
        self.no_genres = QLabel("Genres appear once your shows are matched to AniList.", objectName="Muted")
        gb.addWidget(self.no_genres)
        gb.addStretch(1)

        self.shows_row = CardRow("Most watched", ctx.images)
        self.shows_row.cardActivated.connect(lambda card: self.openItem.emit(card.payload))
        self.note = QLabel("", objectName="SettingsNote", wordWrap=True)

        self.content = QWidget()
        c = QVBoxLayout(self.content)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(18)
        c.addLayout(tiles)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        mid.addWidget(chart_box, 3)
        mid.addWidget(genre_box, 2)
        c.addLayout(mid)
        c.addWidget(self.shows_row)
        c.addWidget(self.note)

        body = QWidget(objectName="PageBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(44, 36, 44, 40)
        col.setSpacing(14)
        col.addWidget(title)
        col.addWidget(self.subtitle)
        col.addWidget(self.empty)
        col.addWidget(self.content)
        col.addStretch(1)
        self.setWidget(body)
        self.content.setVisible(False)
        self.empty.setVisible(False)

    def refresh(self) -> None:
        catalog = self.ctx.catalog
        self.ctx.runner.submit(core_stats.compute, self.ctx.store, catalog.anilist.media, None, catalog.enrich,
                               on_done=self._show, group="stats")

    def _show(self, st: Stats) -> None:
        self.stats = st
        self.empty.setVisible(st.empty)
        self.content.setVisible(not st.empty)
        if st.empty:
            self.subtitle.setText("")
            return
        days = st.total_seconds / 86400
        self.subtitle.setText(f"That's {days:.1f} days of anime." if days >= 1 else "Off to a good start.")
        estimated = st.estimated_seconds and st.estimated_seconds >= st.total_seconds * 0.02
        self.time.set(hours_text(st.total_seconds), "partly estimated" if estimated else "")
        self.episodes.set(f"{st.episodes:,}")
        self.started.set(f"{st.shows_started:,}")
        self.finished.set(f"{st.shows_finished:,}")
        self.streak.set(f"{st.streak_days} day{'s' if st.streak_days != 1 else ''}",
                        f"Best: {st.best_streak_days}" if st.best_streak_days > st.streak_days else "")
        self.week.setText(f"This week {hours_text(st.week_seconds)}  ·  This month {hours_text(st.month_seconds)}")
        self.chart.set_weeks(st.weeks)
        self.genres.set_rows(st.top_genres)
        self.genres.setVisible(bool(st.top_genres))
        self.no_genres.setVisible(not st.top_genres)
        self.shows_row.set_cards([
            Card(key=f"show:{s.anime_id}", title=s.title, cover=s.poster,
                 subtitle=f"{hours_text(s.seconds)} · {s.episodes} ep{'s' if s.episodes != 1 else ''}",
                 payload=self.ctx.store.get_show(s.anime_id))
            for s in st.top_shows if self.ctx.store.get_show(s.anime_id)
        ])
        for s in st.top_shows:  # imported shows can lack a cover; find one like Home does
            if not s.poster:
                self.ctx.runner.submit(self.ctx.catalog.cover_for, s.anime_id, s.title,
                                       on_done=lambda url, aid=s.anime_id: url and self.shows_row.model().update_card(
                                           f"show:{aid}", cover=url))
        self.note.setText("Time watched is exact from AniGUI 1.3 on. Episodes watched earlier, or with ani-cli in "
                          "Terminal, are estimated from their length (24 minutes if unknown)." if estimated else "")
        self.note.setVisible(bool(estimated))
