"""Offline doubles for rendering and testing the UI: invented shows, generated art."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtCore import QSettings

from core import http
from core.ani_cli import StreamInfo
from core.anilist import AniListClient
from core.catalog import Catalog
from core.covers import CoverCache
from core.hianime import Episode, SearchResult
from core.store import Store
from core.tasks import TaskRunner
from ui.context import AppContext
from ui.images import ImageLoader

SHOWS = [
    # title, romaji, format, eps, score, year, genres, color
    ("Starfall Academy", "Hoshifuri Gakuen", "TV", 24, 88, 2026, ["Action", "Fantasy"], "#e4723c"),
    ("The Lantern Keeper", "Chouchin no Bannin", "TV", 12, 84, 2026, ["Drama", "Mystery"], "#4f7ae4"),
    ("Ashen Blade", "Kaijin no Tsurugi", "TV", 13, 81, 2026, ["Action", "Adventure"], "#c94a5a"),
    ("Neon Courier", "Neon Kuriya", "ONA", 10, 79, 2026, ["Sci-Fi", "Action"], "#a356e8"),
    ("Tea House on Cloud Street", "Kumo-dori no Chaya", "TV", 12, 86, 2025, ["Slice of Life"], "#5cb88a"),
    ("Moonlit Detective Club", "Tsukiyo Tantei-bu", "TV", 24, 77, 2026, ["Mystery", "Comedy"], "#3f8fd6"),
    ("Iron Orchard", "Tetsu no Kajuen", "TV", 12, 73, 2026, ["Sci-Fi", "Drama"], "#8a8f9c"),
    ("Spirit Rail", "Rei no Senro", "MOVIE", 1, 90, 2025, ["Fantasy", "Drama"], "#e0b04a"),
    ("Pocket Dungeon Diaries", "Poketto Danjon Nikki", "TV", 12, 70, 2026, ["Comedy", "Fantasy"], "#e2588f"),
    ("Tidecaller", "Shiomaneki", "TV", 25, 83, 2025, ["Adventure"], "#2fb3c4"),
    ("Paper Crane Requiem", "Orizuru Rekuiemu", "TV", 11, 87, 2026, ["Drama", "Romance"], "#d65f4a"),
    ("Galaxy Noodle Express", "Ginga Ramen Kyuko", "TV", 12, 75, 2026, ["Comedy", "Sci-Fi"], "#f0874a"),
]

SYNOPSIS = ("When a meteor shower opens a gate above the academy, a first-year with no magic "
            "discovers she can hear the stars. Now every faction on campus wants her voice, and "
            "the only person she trusts is the rival who tried to expel her on day one.")


def slug(title: str, i: int) -> str:
    return "-".join(title.lower().replace("'", "").split()) + f"-{1000 + i}"


def media_json(i: int) -> dict:
    title, romaji, fmt, eps, score, year, genres, color = SHOWS[i]
    return {
        "id": 500 + i, "idMal": 900 + i,
        "title": {"english": title, "romaji": romaji, "native": None}, "synonyms": [],
        "coverImage": {"extraLarge": f"fake://cover/{i}", "large": None, "color": color},
        "bannerImage": f"fake://banner/{i}" if fmt != "MOVIE" else None,
        "description": SYNOPSIS, "episodes": eps, "status": "RELEASING" if year == 2026 else "FINISHED",
        "format": fmt, "genres": genres, "averageScore": score, "season": "FALL", "seasonYear": year,
        "nextAiringEpisode": {"episode": 5, "airingAt": 4102444800} if i == 0 else None,
    }


def fake_anilist_transport(payload: bytes) -> http.Response:
    body = json.loads(payload)
    q, v = body["query"], body["variables"]
    if "TRENDING_DESC" in q:
        media = [media_json(i) for i in range(len(SHOWS))]
        data = {"Page": {"media": media}}
    elif "seasonYear: $year" in q:
        data = {"Page": {"media": [media_json(i) for i in (10, 3, 6, 1, 8, 11, 2)]}}
    elif "relations {" in q:
        i = v["id"] - 500
        node = lambda j: {"type": "ANIME", **media_json(j)}  # noqa: E731
        edges = [{"relationType": "SEQUEL", "node": node((i + 2) % len(SHOWS))},
                 {"relationType": "PREQUEL", "node": node((i + 1) % len(SHOWS))},
                 {"relationType": "ADAPTATION", "node": {**node((i + 3) % len(SHOWS)), "type": "MANGA"}}]
        recs = [{"rating": 40 - k, "mediaRecommendation": node((i + 4 + k) % len(SHOWS))} for k in range(5)]
        recs.append({"rating": 0, "mediaRecommendation": node((i + 10) % len(SHOWS))})  # unrated: skipped
        data = {"Media": {"relations": {"edges": edges}, "recommendations": {"nodes": recs}}}
    elif "id_in: $ids" in q:
        data = {"Page": {"media": [media_json(i - 500) for i in v["ids"] if 0 <= i - 500 < len(SHOWS)]}}
    elif "search: $search" in q:
        text = v["search"].lower()
        data = {"Page": {"media": [media_json(i) for i, s in enumerate(SHOWS) if s[0].lower() in text or text in s[0].lower()]}}
    else:
        i = v["id"] - 500
        data = {"Media": media_json(i) if 0 <= i < len(SHOWS) else None}
    return http.Response(200, {}, json.dumps({"data": data}).encode())


class FakeHianime:
    def __init__(self, episodes_per_show: int = 12) -> None:
        self.eps = episodes_per_show

    def search(self, query: str) -> list[SearchResult]:
        q = query.lower()
        hits = [(i, s) for i, s in enumerate(SHOWS) if any(w in s[0].lower() for w in q.split())]
        return [SearchResult(n, slug(s[0], i), s[0], f"fake://cover/{i}") for n, (i, s) in enumerate(hits, start=1)]

    def episodes(self, anime_id: str) -> list[Episode]:
        i = int(anime_id.rsplit("-", 1)[-1]) - 1000
        count = SHOWS[i][3] if 0 <= i < len(SHOWS) else self.eps
        return [Episode(str(n), str(10_000 + n), f"Chapter {n}: The {['Gate', 'Rival', 'Choir', 'Storm'][n % 4]}")
                for n in range(1, count + 1)]


def _png(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def fake_art(url: str) -> bytes:
    kind, _, idx = url.removeprefix("fake://").partition("/")
    i = int(idx)
    color = QColor(SHOWS[i][7])
    w, h = (1600, 420) if kind == "banner" else (460, 690)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, color.lighter(130))
    grad.setColorAt(0.55, color.darker(170))
    grad.setColorAt(1, QColor("#0b0b14"))
    p.fillRect(img.rect(), grad)
    seed = int(hashlib.md5(url.encode()).hexdigest(), 16)
    for k in range(7):
        cx = (seed >> (k * 5)) % w
        cy = (seed >> (k * 7 + 3)) % h
        r = 40 + (seed >> (k * 3)) % (h // 2)
        rg = QRadialGradient(QPointF(cx, cy), r)
        rg.setColorAt(0, QColor(255, 255, 255, 70))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(rg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
    if kind == "cover":
        f = p.font()
        f.setPixelSize(44)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QRectF(30, h - 230, w - 60, 200), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, SHOWS[i][0].upper())
    p.end()
    return _png(img)


class FakeBridge(QObject):
    streamResolved = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, hianime: FakeHianime, fail_episodes: set[str] | None = None) -> None:
        super().__init__()
        self.hianime = hianime
        self.fail_episodes = fail_episodes or set()
        self.requests = []
        self._n = 0

    def resolve(self, req) -> str:
        self._n += 1
        rid = f"fake{self._n}"
        self.requests.append(req)
        results = self.hianime.search(req.query)
        title = results[req.index - 1].title if 0 < req.index <= len(results) else "Unknown"
        if req.episode in self.fail_episodes:
            QTimer.singleShot(30, lambda: self.failed.emit(rid, "No sources found for sub!"))
        else:
            info = StreamInfo(f"https://cdn.example/{rid}.m3u8", "https://embed.example/", f"{title} Episode {req.episode}")
            QTimer.singleShot(30, lambda: self.streamResolved.emit(rid, info))
        return rid

    def cancel(self, request_id: str) -> None:
        pass


class FakeMpv(QObject):
    """A stand-in mpv: listens on the IPC socket, records commands, and can send events."""

    def __init__(self, path: str) -> None:
        super().__init__()
        from PySide6.QtNetwork import QLocalServer

        QLocalServer.removeServer(path)
        self.server = QLocalServer(self)
        assert self.server.listen(path), self.server.errorString()
        self.server.newConnection.connect(self._accept)
        self.client = None
        self.commands: list[list] = []
        self._buf = b""

    def _accept(self) -> None:
        self.client = self.server.nextPendingConnection()
        self.client.readyRead.connect(self._read)

    def _read(self) -> None:
        self._buf += bytes(self.client.readAll())
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            if line.strip():
                msg = json.loads(line)
                self.commands.append(msg["command"])
                self._send({"request_id": msg.get("request_id"), "error": "success", "data": None})
                if msg["command"][0] == "loadfile":  # behave like mpv replacing the file
                    self.send_event("end-file", reason="stop")
                    self.send_event("file-loaded")

    def _send(self, obj: dict) -> None:
        if self.client is not None:
            self.client.write((json.dumps(obj) + "\n").encode())
            self.client.flush()

    def send_event(self, name: str, **fields) -> None:
        self._send({"event": name, **fields})

    def set_prop(self, name: str, value) -> None:
        self._send({"event": "property-change", "id": 1, "name": name, "data": value})

    def named(self, name: str) -> list[list]:
        return [c for c in self.commands if c and c[0] == name]

    def quit(self) -> None:
        self.send_event("shutdown")
        if self.client is not None:
            self.client.disconnectFromServer()
        self.server.close()


class FakePlayer:
    def __init__(self, ipc_path: str | None = None, open_socket: bool = True) -> None:
        import tempfile as _tf

        self.ipc_path = ipc_path or os.path.join(_tf.mkdtemp(prefix="ag-", dir="/tmp"), "mpv.sock")
        self.open_socket = open_socket
        self.launched = []
        self.mpv: FakeMpv | None = None

    def launch(self, info, title=None, *, start=None, preferred=None, track=True) -> str:
        self.launched.append((info, title, start))
        if self.open_socket and track:
            self.mpv = FakeMpv(self.ipc_path)
        return "mpv"


def fake_context(root: Path, with_history: bool = True) -> AppContext:
    store = Store(root / "anigui.db")
    hianime = FakeHianime()
    catalog = Catalog(store, hianime=hianime, anilist=AniListClient(cache=store, transport=fake_anilist_transport))
    if with_history:
        for i, ep, done in ((0, "4", False), (4, "7", True), (9, "12", True)):
            aid = slug(SHOWS[i][0], i)
            store.upsert_show(aid, SHOWS[i][0])
            if done:
                store.mark_watched(aid, ep)
            else:
                store.record_progress(aid, ep, 610, 1420)
        store.upsert_show(slug(SHOWS[10][0], 10), SHOWS[10][0])
        store.set_in_library(slug(SHOWS[4][0], 4), True)
        store.set_in_library(slug(SHOWS[10][0], 10), True)
    settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
    return AppContext(
        store=store, catalog=catalog, runner=TaskRunner(),
        images=ImageLoader(CoverCache(root / "covers", fetcher=fake_art)),
        bridge=FakeBridge(hianime), player=FakePlayer(), settings=settings,
    )
