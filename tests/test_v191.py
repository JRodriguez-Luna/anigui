"""v1.9.1: episode titles with accented letters, and the dub fallback."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.hianime import parse_episodes  # noqa: E402

SLUG = "my-hero-academia-season-6-961"


def page(titles: list[str]) -> str:
    links = "".join(
        f'<a title="{t}" class="ssl-item ep-item" data-number="{n}" data-id="{1000 + n}"\n'
        f'   href="/watch/{SLUG}?ep={1000 + n}"><div>{n}</div></a>\n'
        for n, t in enumerate(titles, start=1))
    return json.dumps({"status": True, "html": f'<div class="ss-list">\n{links}</div>'})   # \\u escapes, like hianime


def test_accented_titles_come_through():
    eps = parse_episodes(page(["A Quiet Beginning", "Keishū", "Pokémon & Friends"]), SLUG)
    assert [(e.number, e.episode_id, e.title) for e in eps] == [
        ("1", "1001", "A Quiet Beginning"), ("2", "1002", "Keishū"), ("3", "1003", "Pokémon & Friends")]
    assert "\\u" in page(["Keishū"])                                      # the raw page really is escaped


def test_html_that_isnt_json_still_parses():
    raw = (f'<a title="Plain" class="ssl-item ep-item" data-number="1" data-id="7" '
           f'href="/watch/{SLUG}?ep=7"></a>')
    assert [(e.number, e.title) for e in parse_episodes(raw, SLUG)] == [("1", "Plain")]
