"""Downloads (2.0): save episodes to watch with no internet.

Right-click an episode → Download. One episode downloads at a time, the rest wait their turn.
Saved episodes play from your Mac automatically (no internet needed) and are listed in
My Library → Downloads. Files go to ~/Movies/AniGUI unless you pick another folder.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QListView, QMenu, QStyle, QStyledItemDelegate

from core import paths
from core.ani_cli import StreamInfo, is_download
from core.downloads import Cancelled, Downloader, DownloadError, safe_name
from core.store import Download

from . import festive, theme

ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass
class Job:
    anime_id: str
    title: str
    episode: str
    state: str = "waiting"          # waiting | finding | saving | failed
    fraction: float = 0.0
    error: str = ""
    cancel: bool = False
    resolve: object = None          # the ResolveJob while finding the stream


def folder(ctx, create: bool = True) -> Path:
    chosen = str(ctx.pref("downloads_folder") or "")
    if chosen and os.path.isabs(chosen):
        path = Path(chosen)
        try:
            if create:
                path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            pass
    return paths.downloads_dir(create)


def size_text(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    return f"{max(1, round(n / (1 << 20)))} MB"


def offline_stream(ctx, anime_id: str, episode: str) -> StreamInfo | None:
    """The saved copy of an episode, if it's still on this Mac."""
    d = ctx.store.download(anime_id, episode)
    if d is None or not is_download(d.video):
        return None
    return StreamInfo(url=d.video, referrer=None, title=d.title,
                      audio_url=d.audio if is_download(d.audio) else None,
                      subtitle_url=d.subtitles if is_download(d.subtitles) else None)


class DownloadManager(QObject):
    changed = Signal()                      # the list or someone's progress changed
    finished = Signal(str, str)             # anime_id, episode
    failed = Signal(str, str, str)          # anime_id, episode, message
    _progress = Signal(object, float)       # (from the worker thread)
    _done = Signal(object, object)          # job, Saved | Exception

    def __init__(self, ctx, resolver, parent=None) -> None:
        super().__init__(parent)
        self.ctx, self.resolver = ctx, resolver
        self.jobs: list[Job] = []
        self.active: Job | None = None
        self._last_emit = 0.0
        self._progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self._done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)

    # -- asking -------------------------------------------------------------------------------

    def job(self, anime_id: str, episode: str) -> Job | None:
        return next((j for j in self.jobs if j.anime_id == anime_id and j.episode == episode), None)

    def state(self, anime_id: str, episode: str) -> str | None:
        """None | "saved" | "waiting" | "42%" (for the episode cards)."""
        j = self.job(anime_id, episode)
        if j is not None and j.state != "failed":
            return f"{int(j.fraction * 100)}%" if j.state == "saving" else "waiting"
        d = self.ctx.store.download(anime_id, episode)
        return "saved" if d is not None and d.present else None

    def states_for(self, anime_id: str):
        """A quick state(episode) for one show's episode cards (one database look)."""
        saved = self.ctx.store.downloaded_episodes(anime_id)
        jobs = {j.episode: j for j in self.jobs if j.anime_id == anime_id and j.state != "failed"}

        def state(episode: str) -> str | None:
            j = jobs.get(episode)
            if j is not None:
                return f"{int(j.fraction * 100)}%" if j.state == "saving" else "waiting"
            return "saved" if episode in saved else None
        return state

    def start(self, anime_id: str, title: str, episode: str) -> bool:
        if self.state(anime_id, episode) is not None:
            return False
        old = self.job(anime_id, episode)
        if old is not None:
            self.jobs.remove(old)                  # a failed one, trying again
        self.jobs.append(Job(anime_id, title, episode))
        self.changed.emit()
        self._next()
        return True

    def cancel(self, anime_id: str, episode: str) -> None:
        j = self.job(anime_id, episode)
        if j is None:
            return
        j.cancel = True
        if j.resolve is not None:
            self.resolver.cancel(j.resolve)
        if j is not self.active or j.state == "finding":
            self.jobs.remove(j)
            if j is self.active:
                self.active = None
                self._next()
        self.changed.emit()

    def remove(self, anime_id: str, episode: str) -> None:
        """Deletes the saved files (not your progress)."""
        d = self.ctx.store.download(anime_id, episode)
        if d is not None:
            for path in (d.video, d.audio, d.subtitles):
                if path and is_download(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            self.ctx.store.remove_download(anime_id, episode)
        j = self.job(anime_id, episode)
        if j is not None and j.state == "failed":
            self.jobs.remove(j)
        self.changed.emit()

    def show_in_finder(self, anime_id: str | None = None, episode: str | None = None) -> None:
        d = self.ctx.store.download(anime_id, episode) if anime_id else None
        target = d.video if d is not None and d.present else str(folder(self.ctx))   # (made if it isn't there)
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target] if d is not None else ["open", target])

    def shutdown(self) -> None:
        for j in self.jobs:
            j.cancel = True

    # -- working ------------------------------------------------------------------------------

    def _next(self) -> None:
        if self.active is not None:
            return
        j = next((j for j in self.jobs if j.state == "waiting"), None)
        if j is None:
            return
        self.active = j
        j.state = "finding"
        self.changed.emit()
        j.resolve = self.resolver.prepare(
            j.anime_id, j.title, j.episode,
            on_ready=lambda info, job=j: self._got_stream(job, info),
            on_fail=lambda msg, job=j: self._on_done(job, DownloadError(msg)),
            online=True,
        )

    def _got_stream(self, j: Job, info: StreamInfo) -> None:
        j.resolve = None
        if j.cancel:
            return
        j.state = "saving"
        self.changed.emit()
        show_dir = folder(self.ctx) / safe_name(j.title)
        name = f"{j.title} - Episode {j.episode}"
        worker = Downloader(progress=lambda f, job=j: self._progress.emit(job, f), cancelled=lambda job=j: job.cancel)

        def run():
            try:
                result = worker.download(info, show_dir, name)
            except BaseException as exc:  # noqa: BLE001 (reported back on the main thread)
                result = exc
            self._done.emit(j, result)

        threading.Thread(target=run, name=f"download {j.anime_id} {j.episode}", daemon=True).start()

    def _on_progress(self, j: Job, fraction: float) -> None:
        j.fraction = fraction
        now = time.monotonic()
        if now - self._last_emit >= 0.25 or fraction >= 1.0:
            self._last_emit = now
            self.changed.emit()

    def _on_done(self, j: Job, result) -> None:
        if j is self.active:
            self.active = None
        if isinstance(result, Cancelled) or j.cancel:
            if j in self.jobs:
                self.jobs.remove(j)
        elif isinstance(result, BaseException):
            j.state, j.error = "failed", str(result) or "Something went wrong."
            self.failed.emit(j.anime_id, j.episode, j.error)
        else:
            self.ctx.store.add_download(j.anime_id, j.episode, str(result.video),
                                        str(result.audio) if result.audio else None,
                                        str(result.subtitles) if result.subtitles else None, result.size)
            self.jobs.remove(j)
            self.finished.emit(j.anime_id, j.episode)
        self.changed.emit()
        self._next()


# -- My Library → Downloads ---------------------------------------------------------------------

class DownloadDelegate(QStyledItemDelegate):
    ROW_H = 76

    def __init__(self, images, parent=None) -> None:
        super().__init__(parent)
        self.images = images

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        kind, value = index.data(ROLE)
        r = QRectF(option.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_MouseOver:
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(0, 2, -4, -2), 10, 10)
            p.fillPath(path, QColor(255, 255, 255, 14))
        title, episode = value.title, value.episode
        poster = self.ctx_poster(value.anime_id) or getattr(value, "poster", None)   # (the cover may come later)
        thumb = QRectF(r.left() + 10, r.top() + 8, 43, 60)
        pm = self.images.pixmap(poster, int(thumb.width()), int(thumb.height())) if poster else None
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 6, 6)
        p.setClipPath(clip)
        if pm is not None:
            p.drawPixmap(thumb.toRect(), pm)
        else:
            p.fillRect(thumb, QColor(theme.SURFACE_2))
        p.setClipping(False)
        x = thumb.right() + 14
        w = r.right() - x - 20
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(14, QFont.Weight.DemiBold))
        p.drawText(QRectF(x, r.top() + 14, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(f"{title} · Episode {episode}", Qt.TextElideMode.ElideRight, int(w)))
        p.setFont(theme.font(12, QFont.Weight.Medium))
        if kind == "job":
            if value.state == "failed":
                p.setPen(QColor("#FF8A80"))
                text = f"Couldn't save it: {value.error}  ·  Right-click to try again"
            elif value.state == "saving":
                p.setPen(QColor(theme.MUTED))
                text = f"Downloading… {int(value.fraction * 100)}%"
                bar = QRectF(x, r.top() + 58, min(320.0, w), 4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 2, 2)
                festive.progress_bar(p, bar, max(0.02, value.fraction), theme.ACCENT)
                p.setPen(QColor(theme.MUTED))
            else:
                p.setPen(QColor(theme.MUTED))
                text = "Finding the stream…" if value.state == "finding" else "Waiting its turn"
        else:
            p.setPen(QColor(theme.MUTED if value.present else "#FF8A80"))
            text = (f"On this Mac · {size_text(value.size)} · plays with no internet" if value.present
                    else "The file was moved or deleted · Right-click to remove it")
        p.drawText(QRectF(x, r.top() + 36, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(w)))
        p.restore()

    ctx_poster = staticmethod(lambda _aid: None)


class DownloadsView(QListView):
    play = Signal(str, str, str)            # anime_id, title, episode

    def __init__(self, ctx, manager: DownloadManager, parent=None) -> None:
        super().__init__(parent)
        self.ctx, self.manager = ctx, manager
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.delegate = DownloadDelegate(ctx.images, self)

        def poster(aid):
            show = ctx.store.get_show(aid)
            return show.poster if show else None

        self.delegate.ctx_poster = poster
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setObjectName("Timeline")
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._clicked)
        ctx.images.loaded.connect(lambda _u: self.viewport().update())

    def rows(self) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = [("job", j) for j in self.manager.jobs]
        out += [("saved", d) for d in self.ctx.store.downloads()]
        return out

    def refresh(self) -> int:
        rows = self.rows()
        self.model_.clear()
        for row in rows:
            item = QStandardItem()
            item.setData(row, ROLE)
            self.model_.appendRow(item)
        return len(rows)

    def _clicked(self, index: QModelIndex) -> None:
        kind, value = index.data(ROLE)
        if kind == "saved" and value.present:
            self.play.emit(value.anime_id, value.title, value.episode)

    def contextMenuEvent(self, e) -> None:
        index = self.indexAt(e.pos())
        if not index.isValid():
            return
        kind, v = index.data(ROLE)
        m = self.manager
        menu = QMenu(self)
        if kind == "job":
            if v.state == "failed":
                menu.addAction("Try again").triggered.connect(lambda: m.start(v.anime_id, v.title, v.episode))
                menu.addAction("Remove").triggered.connect(lambda: m.remove(v.anime_id, v.episode))
            else:
                menu.addAction("Cancel download").triggered.connect(lambda: m.cancel(v.anime_id, v.episode))
        else:
            d: Download = v
            if d.present:
                menu.addAction("Play").triggered.connect(lambda: self.play.emit(d.anime_id, d.title, d.episode))
                menu.addAction("Show in Finder").triggered.connect(lambda: m.show_in_finder(d.anime_id, d.episode))
            menu.addAction("Remove download").triggered.connect(lambda: m.remove(d.anime_id, d.episode))
        menu.exec(e.globalPos())
