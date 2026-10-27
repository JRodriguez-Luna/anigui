"""Tiny HTTP helper over urllib with certifi, so python.org builds on macOS verify TLS too."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL = ssl.create_default_context()

USER_AGENT = "AniGUI/0.1 (+https://github.com/pystardust/ani-cli frontend)"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
            timeout: float = 15.0) -> Response:
    """Return a Response for any HTTP status. Raises OSError only for network failures."""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b"")
