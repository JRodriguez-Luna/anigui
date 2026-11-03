"""The GitHub release notes for a version: What's New (the same text as the in-app
window, from core/changelog.py), then the install steps (packaging/RELEASE_NOTES.md).

    python tools/release_notes.py 1.8.8 > notes.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import changelog  # noqa: E402


def notes(version: str) -> str:
    release = next((r for r in changelog.RELEASES if r.version == version), None)
    if release is None:
        raise SystemExit(f"core/changelog.py has no entry for {version}")
    lines = ["## What's new", ""] + [f"- **{c.title}:** {c.text}" for c in release.changes] + [""]
    install = (ROOT / "packaging" / "RELEASE_NOTES.md").read_text().replace("{{VERSION}}", version)
    return "\n".join(lines) + "\n" + install


if __name__ == "__main__":
    sys.stdout.write(notes(sys.argv[1]))
