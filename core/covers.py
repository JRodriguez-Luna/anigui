"""On-disk image cache for covers and banners.

Files are keyed by a hash of the URL and written atomically, so a half-finished
download never shows up as a broken image. Hits refresh the file's mtime, and
prune() trims the oldest files once the cache passes its size budget.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import http, paths

DEFAULT_BUDGET = 400 * 1024 * 1024  # 400 MB

Fetcher = Callable[[str], bytes]

_SIGNATURES = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"GIF8": ".gif",
}


class CoverError(RuntimeError):
    pass


def _default_fetcher(url: str) -> bytes:
    headers = {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if "anilist.co" not in url:
        headers["Referer"] = "https://hianime.at/"  # hianime's image CDN checks this
    try:
        resp = http.request(url, headers=headers, timeout=20)
    except OSError as exc:
        raise CoverError(f"Could not download {url}: {exc}") from exc
    if resp.status != 200:
        raise CoverError(f"HTTP {resp.status} for {url}")
    return resp.body


def image_extension(data: bytes) -> str | None:
    for sig, ext in _SIGNATURES.items():
        if data.startswith(sig):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    return None


class CoverCache:
    def __init__(self, directory: str | Path | None = None, fetcher: Fetcher | None = None,
                 budget_bytes: int = DEFAULT_BUDGET) -> None:
        self.dir = Path(directory) if directory else paths.covers_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher or _default_fetcher
        self.budget = budget_bytes

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def cached_path(self, url: str) -> Path | None:
        """Path to the cached image if present. Cheap enough for the UI thread."""
        key = self._key(url)
        for path in self.dir.glob(key + ".*"):
            if path.suffix != ".part":
                return path
        return None

    def get(self, url: str) -> Path:
        """Return a local file for url, downloading it if needed. Call from a worker thread."""
        hit = self.cached_path(url)
        if hit:
            try:
                os.utime(hit)
            except OSError:
                pass
            return hit

        data = self.fetcher(url)
        ext = image_extension(data)
        if not ext:
            raise CoverError(f"Not an image: {url}")

        target = self.dir / (self._key(url) + ext)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return target

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.dir.iterdir() if p.is_file())

    def prune(self) -> int:
        """Delete least-recently-used files until under budget. Returns files removed."""
        files = [p for p in self.dir.iterdir() if p.is_file()]
        hour_ago = time.time() - 3600
        for p in files:  # leftovers from interrupted downloads; recent ones may be in flight
            if p.suffix == ".part" and p.stat().st_mtime < hour_ago:
                p.unlink(missing_ok=True)
        files = sorted((p for p in files if p.suffix != ".part"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        removed = 0
        for p in files:
            if total <= self.budget:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
            removed += 1
        return removed
