"""Playback: resolve streams, run the player, track progress, auto-play the next episode.

    PlaybackController.play(anime_id, title, episode)
        -> StreamResolver: locate the show for ani-cli -S, resolve with ani-cli
        -> live Session? load into the open player : launch IINA/mpv with an IPC socket
        -> Session: save position every few seconds, mark watched at 90%,
           prefetch the next episode near the end, count down and load it at EOF.

Without IPC (the player never opened its socket) playback still works; it just
isn't tracked, same as Step 3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from core import aniskip
from core.ani_cli import StreamInfo
from core.catalog import CatalogError
from core.mpv_ipc import MpvIpc
from core.player import PLAYER_NAMES

from .context import AppContext

SAVE_EVERY_S = 5.0
PREFETCH_REMAINING_S = 120.0
COUNTDOWN_S = 5
RESUME_MIN_S = 30.0          # don't bother resuming the first 30 seconds
RESUME_TAIL_S = 60.0         # or the last minute (credits)
IPC_TIMEOUT_MS = 12_000


def media_title(title: str, episode: str) -> str:
    return f"{title} — Episode {episode}"


# -- Resolving ----------------------------------------------------------------------------

@dataclass
class ResolveJob:
    anime_id: str
    title: str
    episode: str
    on_ready: Callable[[StreamInfo], None]
    on_fail: Callable[[str], None]
    on_status: Callable[[str], None] = lambda _s: None
    retried: bool = False
    cancelled: bool = False
    request_id: str | None = None
    dub: bool | None = None          # None = follow the Sub/Dub preference
    fell_back_to_sub: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class StreamResolver(QObject):
    """Turns (show, episode) into a StreamInfo. Several jobs can run at once."""

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._jobs: dict[str, ResolveJob] = {}
        ctx.bridge.streamResolved.connect(self._on_resolved)
        ctx.bridge.failed.connect(self._on_failed)

    def prepare(self, anime_id: str, title: str, episode: str, on_ready, on_fail, on_status=None) -> ResolveJob:
        job = ResolveJob(anime_id, title, episode, on_ready, on_fail, on_status or (lambda _s: None))
        self._locate(job)
        return job

    def cancel(self, job: ResolveJob | None) -> None:
        if job is None:
            return
        job.cancel()
        if job.request_id:
            self._jobs.pop(job.request_id, None)
            self.ctx.bridge.cancel(job.request_id)

    def _locate(self, job: ResolveJob) -> None:
        job.on_status("Finding stream…")
        self.ctx.runner.submit(
            self.ctx.catalog.play_request, job.anime_id, job.episode, title=job.title,
            dub=self.ctx.pref("dub", False) if job.dub is None else job.dub,
            quality=str(self.ctx.pref("quality", "best")),
            on_done=lambda req, j=job: self._resolve(j, req),
            on_error=lambda msg, j=job: self._fail(j, msg),
        )

    def _resolve(self, job: ResolveJob, request) -> None:
        if job.cancelled:
            return
        job.on_status("Resolving stream…")
        job.request_id = self.ctx.bridge.resolve(request)
        self._jobs[job.request_id] = job

    def _on_resolved(self, request_id: str, info: StreamInfo) -> None:
        job = self._jobs.pop(request_id, None)
        if job is None or job.cancelled:
            return
        try:
            self.ctx.catalog.verify_stream(job.anime_id, info.title)
        except CatalogError:
            if not job.retried:  # search order shifted under us; look it up again once
                job.retried, job.request_id = True, None
                self._locate(job)
                return
            self._fail(job, "ani-cli kept picking a different show. Try searching for it again.")
            return
        job.on_ready(info)

    def _on_failed(self, request_id: str, message: str) -> None:
        job = self._jobs.pop(request_id, None)
        if job is None or job.cancelled:
            return
        if "no sources found for dub" in message.lower() and not job.fell_back_to_sub:
            # Not every episode has a dub; play it subbed instead of failing.
            job.dub, job.fell_back_to_sub, job.request_id = False, True, None
            job.on_status("No dub for this episode, trying sub…")
            self._locate(job)
            return
        self._fail(job, message)

    @staticmethod
    def _fail(job: ResolveJob, message: str) -> None:
        if not job.cancelled:
            job.on_fail(message)


# -- A running player ---------------------------------------------------------------------

@dataclass
class _Now:
    anime_id: str
    title: str
    episode: str
    position: float | None = None
    duration: float | None = None
    last_save: float = 0.0
    pending_tracks: list[tuple[str, str]] = field(default_factory=list)
    skips: list[aniskip.Segment] | None = None   # None until looked up
    skipped: set[str] = field(default_factory=set)


class Session(QObject):
    """One player window, possibly playing several episodes in a row."""

    saved = Signal(str, str)            # anime_id, episode
    episodeChanged = Signal(str, str)   # auto-next moved on
    notice = Signal(str, bool)          # message, is_error
    ended = Signal()
    untracked = Signal()                # player never opened its control socket

    def __init__(self, ctx: AppContext, resolver: StreamResolver, kind: str, ipc_path: str,
                 anime_id: str, title: str, episode: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.resolver, self.kind = ctx, resolver, kind
        self.now = _Now(anime_id, title, episode)
        self.episodes: list[str] | None = None
        self.next_job: ResolveJob | None = None
        self.next_info: StreamInfo | None = None
        self.advance_when_ready = False
        self.loading = False
        self.closed = False
        self._next_episode: str | None = None
        self._countdown_left = 0
        self._countdown = QTimer(self, interval=1000)
        self._countdown.timeout.connect(self._tick)

        self.ipc = MpvIpc(ipc_path, self)
        self.ipc.connected.connect(self._on_connected)
        self.ipc.gaveUp.connect(self._on_gave_up)
        self.ipc.disconnected.connect(self._on_closed)
        self.ipc.propertyChanged.connect(self._on_property)
        self.ipc.event.connect(self._on_event)
        self.ipc.start(IPC_TIMEOUT_MS)
        self._load_episode_list()

    @property
    def alive(self) -> bool:
        return not self.closed and self.ipc.is_connected

    # -- control ------------------------------------------------------------------------

    def load(self, info: StreamInfo, anime_id: str, title: str, episode: str, start: float | None) -> None:
        """Play another episode in this same player window."""
        self.save()
        self._countdown.stop()
        same_show = anime_id == self.now.anime_id
        self._cancel_next()
        self.now = _Now(anime_id, title, episode)
        if not same_show:
            self.episodes = None
            self._load_episode_list()
        self.loading = True
        self.ipc.command("set_property", "options/referrer", info.referrer or "")
        self.ipc.command("set_property", "force-media-title", media_title(title, episode))
        self.ipc.command("set_property", "options/start", f"{start:.0f}" if start else "none")
        self.now.pending_tracks = [("audio-add", info.audio_url)] if info.audio_url else []
        if info.subtitle_url:
            self.now.pending_tracks.append(("sub-add", info.subtitle_url))
        self.ipc.command("loadfile", info.url, "replace")

    def save(self) -> None:
        n = self.now
        if n.position is None:
            return
        self.ctx.store.record_progress(n.anime_id, n.episode, n.position, n.duration)
        n.last_save = time.monotonic()
        self.saved.emit(n.anime_id, n.episode)

    def close(self) -> None:
        self._on_closed()

    # -- IPC events ---------------------------------------------------------------------

    def _on_connected(self) -> None:
        for name in ("time-pos", "duration", "pause"):
            self.ipc.observe(name)

    def _on_gave_up(self) -> None:
        self.closed = True
        self.untracked.emit()

    def _on_closed(self) -> None:
        if self.closed:
            return
        self.save()
        self.closed = True
        self._countdown.stop()
        self._cancel_next()
        self.ipc.stop()
        self.ended.emit()

    def _on_property(self, name: str, value) -> None:
        n = self.now
        if name == "time-pos" and isinstance(value, (int, float)) and not self.loading:
            n.position = float(value)
            if self._maybe_skip(n.position):
                return
            if time.monotonic() - n.last_save >= SAVE_EVERY_S:
                self.save()
            self._maybe_prefetch()
        elif name == "duration" and isinstance(value, (int, float)) and value > 0 and not self.loading:
            n.duration = float(value)
            self._lookup_skips()
        elif name == "pause" and value is True:
            self.save()

    def _on_event(self, name: str, msg: dict) -> None:
        if name == "file-loaded":
            self.loading = False
            for cmd, url in self.now.pending_tracks:
                self.ipc.command(cmd, url, "select")
            self.now.pending_tracks = []
        elif name == "end-file":
            reason = msg.get("reason")
            if reason == "eof":
                if self.now.duration:
                    self.now.position = self.now.duration  # count the credits as watched
                self.save()
                self._advance()
            elif reason == "error" and not self.loading:
                self.notice.emit("The player couldn't play this stream.", True)
            elif not self.loading:
                self.save()
        elif name == "shutdown":
            self._on_closed()

    # -- skipping (AniSkip times, applied through the control socket) -------------------

    SKIP_PREFS = {"intro": "skip_intro", "ending": "skip_ending", "recap": "skip_recap"}
    SKIP_TEXT = {"intro": "Skipped intro", "ending": "Skipped ending", "recap": "Skipped recap"}

    def _skip_kinds(self) -> set[str]:
        return {kind for kind, key in self.SKIP_PREFS.items() if self.ctx.pref(key)}

    def _lookup_skips(self) -> None:
        n = self.now
        if n.skips is not None or not self._skip_kinds():
            return
        n.skips = []  # looking it up

        def find(aid=n.anime_id, title=n.title, ep=n.episode, duration=n.duration):
            mal = self.ctx.catalog.mal_id(aid, title)
            return aniskip.skip_times(mal, ep, duration, cache=self.ctx.store) if mal else []

        def done(segments, aid=n.anime_id, ep=n.episode):
            if (self.now.anime_id, self.now.episode) == (aid, ep):
                self.now.skips = segments

        self.ctx.runner.submit(find, on_done=done)

    def _maybe_skip(self, position: float) -> bool:
        n = self.now
        if not n.skips:
            return False
        kinds = self._skip_kinds()
        for seg in n.skips:
            if seg.kind in kinds and seg.kind not in n.skipped and seg.contains(position):
                n.skipped.add(seg.kind)  # once per episode, so seeking back into it is allowed
                target = seg.end if not n.duration else min(seg.end, n.duration)
                self.ipc.command("seek", f"{target:.2f}", "absolute")
                self.ipc.command("show-text", self.SKIP_TEXT[seg.kind], 2000)
                return True
        return False

    # -- auto-next ----------------------------------------------------------------------

    def _load_episode_list(self) -> None:
        anime_id = self.now.anime_id
        self.ctx.runner.submit(
            self.ctx.catalog.episodes, anime_id,
            on_done=lambda eps, aid=anime_id: aid == self.now.anime_id and setattr(self, "episodes", [e.number for e in eps]),
        )

    def _next_number(self) -> str | None:
        if not self.episodes or self.now.episode not in self.episodes:
            return None
        i = self.episodes.index(self.now.episode)
        return self.episodes[i + 1] if i + 1 < len(self.episodes) else None

    def _maybe_prefetch(self) -> None:
        n = self.now
        if (self.next_job or self.next_info or not n.duration or n.position is None
                or n.duration - n.position > PREFETCH_REMAINING_S or not self.ctx.pref("autoplay", True)):
            return
        nxt = self._next_number()
        if nxt:
            self._prefetch(nxt)

    def _prefetch(self, episode: str) -> None:
        n = self.now
        self.next_job = self.resolver.prepare(
            n.anime_id, n.title, episode,
            on_ready=lambda info, ep=episode, aid=n.anime_id: self._next_ready(aid, ep, info),
            on_fail=lambda msg, ep=episode: self._next_failed(ep, msg),
        )

    def _next_ready(self, anime_id: str, episode: str, info: StreamInfo) -> None:
        if anime_id != self.now.anime_id or self.closed:
            return
        self.next_job, self.next_info = None, info
        self._next_episode = episode
        if self.advance_when_ready:
            self.advance_when_ready = False
            self._play_next()

    def _next_failed(self, episode: str, message: str) -> None:
        self.next_job = None
        if self.advance_when_ready:
            self.advance_when_ready = False
            self.ipc.command("show-text", f"Couldn't load episode {episode}", 4000)
            self.notice.emit(f"Couldn't auto-play episode {episode}: {message}", True)

    def _cancel_next(self) -> None:
        self.resolver.cancel(self.next_job)
        self.next_job, self.next_info, self.advance_when_ready = None, None, False

    def _advance(self) -> None:
        if not self.ctx.pref("autoplay", True):
            return
        nxt = self._next_number()
        if nxt is None:
            if self.episodes is not None:
                self.ipc.command("show-text", "That was the last episode", 4000)
            return
        self._next_episode = nxt
        self._countdown_left = COUNTDOWN_S
        self._tick()
        self._countdown.start()
        if not self.next_info and not self.next_job:
            self._prefetch(nxt)

    def _tick(self) -> None:
        if self._countdown_left <= 0:
            self._countdown.stop()
            if self.next_info:
                self._play_next()
            else:
                self.advance_when_ready = True
                self.ipc.command("show-text", f"Loading episode {self._next_episode}…", 30_000)
            return
        self.ipc.command("show-text", f"Episode {self._next_episode} starts in {self._countdown_left}…", 1100)
        self._countdown_left -= 1

    def _play_next(self) -> None:
        info, episode = self.next_info, self._next_episode
        n = self.now
        self.next_info = None
        self.load(info, n.anime_id, n.title, episode, None)
        self.ctx.store.record_progress(n.anime_id, episode, 0.0)
        self.episodeChanged.emit(n.anime_id, episode)


# -- Front door used by the pages -----------------------------------------------------------

class PlaybackController(QObject):
    busy = Signal(str, str, str)       # anime_id, episode, status text
    started = Signal(str, str, str)    # anime_id, episode, player kind
    failed = Signal(str, str, str)     # anime_id, episode, message
    progressSaved = Signal(str, str)   # anime_id, episode
    episodeChanged = Signal(str, str)  # anime_id, episode (auto-next)
    sessionEnded = Signal()
    notice = Signal(str, bool)         # message, is_error

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.resolver = StreamResolver(ctx, self)
        self.session: Session | None = None
        self._job: ResolveJob | None = None

    @property
    def active(self) -> tuple[str, str] | None:
        return (self._job.anime_id, self._job.episode) if self._job else None

    @property
    def now_playing(self) -> tuple[str, str] | None:
        if self.session and self.session.alive:
            return self.session.now.anime_id, self.session.now.episode
        return None

    def play(self, anime_id: str, title: str, episode: str) -> None:
        self.cancel()
        job = self.resolver.prepare(
            anime_id, title, episode,
            on_ready=lambda info: self._start(job, info),
            on_fail=lambda msg: self._fail(job, msg),
            on_status=lambda text: self.busy.emit(anime_id, episode, text),
        )
        self._job = job

    def cancel(self) -> None:
        if self._job:
            self.resolver.cancel(self._job)
        self._job = None

    def resume_position(self, anime_id: str, episode: str) -> float | None:
        p = self.ctx.store.get_progress(anime_id, episode)
        if not p or p.completed or p.position < RESUME_MIN_S:
            return None
        if p.duration and p.position > p.duration - RESUME_TAIL_S:
            return None
        return p.position

    def _start(self, job: ResolveJob, info: StreamInfo) -> None:
        if job is not self._job:
            return
        self._job = None
        start = self.resume_position(job.anime_id, job.episode)
        if self.session and self.session.alive:
            self.session.load(info, job.anime_id, job.title, job.episode, start)
            kind = self.session.kind
        else:
            try:
                kind = self.ctx.player.launch(
                    info, media_title(job.title, job.episode), start=start,
                    preferred=str(self.ctx.pref("player", "auto")),
                )
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(job.anime_id, job.episode, str(exc))
                return
            self._new_session(kind, job)
        if not self.ctx.store.get_progress(job.anime_id, job.episode):
            self.ctx.store.record_progress(job.anime_id, job.episode, 0.0)
        self.started.emit(job.anime_id, job.episode, kind)
        wanted = str(self.ctx.pref("player", "auto"))
        if wanted in PLAYER_NAMES and kind != wanted:
            self.notice.emit(f"{PLAYER_NAMES[wanted]} isn't installed, so this opened in {PLAYER_NAMES[kind]}. "
                             f"Open Setup to install {PLAYER_NAMES[wanted]}." if wanted == "iina" else
                             f"{PLAYER_NAMES[wanted]} isn't installed, so this opened in {PLAYER_NAMES[kind]}.", False)
        elif job.fell_back_to_sub:
            self.notice.emit(f"Episode {job.episode} has no dub on hianime yet, so it's playing subbed.", False)
        elif start:
            mins, secs = divmod(int(start), 60)
            self.notice.emit(f"Resuming episode {job.episode} at {mins}:{secs:02d}", False)

    def _new_session(self, kind: str, job: ResolveJob) -> None:
        if self.session:
            self.session.close()
            self.session.deleteLater()
        s = Session(self.ctx, self.resolver, kind, self.ctx.player.ipc_path,
                    job.anime_id, job.title, job.episode, self)
        s.saved.connect(self.progressSaved)
        s.episodeChanged.connect(self.episodeChanged)
        s.notice.connect(self.notice)
        s.ended.connect(self.sessionEnded)
        s.untracked.connect(lambda k=kind: self._untracked(k))
        self.session = s

    def _untracked(self, kind: str) -> None:
        if kind == "iina":
            self.notice.emit("Playing without progress tracking: IINA didn't open mpv's control channel. "
                             "Quit IINA and try again, or choose mpv in Settings → Playback.", True)
        else:
            self.notice.emit("Playing without progress tracking: couldn't connect to the player.", True)

    def _fail(self, job: ResolveJob, message: str) -> None:
        if job is self._job:
            self._job = None
            self.failed.emit(job.anime_id, job.episode, message)

    def shutdown(self) -> None:
        self.cancel()
        if self.session:
            self.session.save()
