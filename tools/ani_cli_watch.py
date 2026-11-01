#!/usr/bin/env python3
"""Watch for new ani-cli versions (used by .github/workflows/ani-cli-watch.yml).

ani-cli publishes fixes by raising `version_number` in the script on its master
branch (that's also what `ani-cli -U` installs). AniGUI pins one exact,
checksum-verified copy (core/setup.py), so a new ani-cli only reaches people
through a new AniGUI release. This tool finds a newer ani-cli and rewrites the pin.

    python tools/ani_cli_watch.py check
        Prints the newest ani-cli on master and whether it's newer than the pin.
        In GitHub Actions it also writes: new, version, pinned, commit, sha256.

    python tools/ani_cli_watch.py bump VERSION COMMIT SHA256
        Points core/setup.py, the tests workflow and the README at that ani-cli.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import setup  # noqa: E402

ANI_CLI_GIT = "https://github.com/pystardust/ani-cli"
BRANCH = "master"

VERSION_RE = re.compile(r"\d+(\.\d+){1,3}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Candidate:
    version: str
    commit: str
    sha256: str
    pinned: str

    @property
    def new(self) -> bool:
        return setup.parse_version(self.version) > setup.parse_version(self.pinned)


def master_commit(run=subprocess.run) -> str:
    out = run(["git", "ls-remote", ANI_CLI_GIT, f"refs/heads/{BRANCH}"],
              capture_output=True, text=True, timeout=60)
    commit = out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else ""
    if not COMMIT_RE.fullmatch(commit):
        raise SystemExit(f"Couldn't read ani-cli's {BRANCH} branch: {out.stderr.strip()[:200]}")
    return commit


def check(fetch=setup._fetch, run=subprocess.run) -> Candidate:
    """The ani-cli script at the current master commit (fetched by commit, so it can't move)."""
    commit = master_commit(run)
    script = fetch(setup.ANI_CLI_RAW.format(ref=commit))
    version = setup.script_version(script) or ""
    if not script.startswith(b"#!") or not VERSION_RE.fullmatch(version):
        raise SystemExit(f"ani-cli at {commit[:7]} doesn't look like the ani-cli script.")
    return Candidate(version, commit, hashlib.sha256(script).hexdigest(), setup.ANI_CLI_PIN_VERSION)


# -- bump -----------------------------------------------------------------------------

def _sub(text: str, pattern: str, repl: str, path: str) -> str:
    new, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n == 0:
        raise SystemExit(f"{path}: couldn't find {pattern!r}")
    return new


def bump_texts(texts: dict[str, str], version: str, commit: str, sha256: str) -> dict[str, str]:
    """Rewrite the pin in each file's text. Keys are repo-relative paths."""
    if not (VERSION_RE.fullmatch(version) and COMMIT_RE.fullmatch(commit) and SHA256_RE.fullmatch(sha256)):
        raise SystemExit("bump: version, commit or checksum is malformed")
    rules = {
        "core/setup.py": [
            (r'^ANI_CLI_PIN_VERSION = "[^"]*"', f'ANI_CLI_PIN_VERSION = "{version}"'),
            (r'^ANI_CLI_PIN_COMMIT = "[^"]*"', f'ANI_CLI_PIN_COMMIT = "{commit}"'),
            (r'^ANI_CLI_PIN_SHA256 = "[^"]*"', f'ANI_CLI_PIN_SHA256 = "{sha256}"'),
        ],
        ".github/workflows/tests.yml": [
            (r"^(\s*# ani-cli )[\d.]+(, the version)", rf"\g<1>{version}\2"),
            (r"^(\s*ANI_CLI_COMMIT: )[0-9a-f]+", rf"\g<1>{commit}"),
        ],
        "README.md": [
            (r"tested against ani-cli \*\*[\d.]+\*\*", f"tested against ani-cli **{version}**"),
        ],
    }
    out = {}
    for path, subs in rules.items():
        text = texts[path]
        for pattern, repl in subs:
            text = _sub(text, pattern, repl, path)
        out[path] = text
    return out


def bump(version: str, commit: str, sha256: str, root: Path = ROOT) -> list[str]:
    paths = ["core/setup.py", ".github/workflows/tests.yml", "README.md"]
    old = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    new = bump_texts(old, version, commit, sha256)
    changed = [p for p in paths if new[p] != old[p]]
    for p in changed:
        (root / p).write_text(new[p], encoding="utf-8")
    return changed


# -- CLI ------------------------------------------------------------------------------

def _github_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    b = sub.add_parser("bump")
    b.add_argument("version")
    b.add_argument("commit")
    b.add_argument("sha256")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        c = check()
        print(json.dumps({"pinned": c.pinned, "latest": c.version, "commit": c.commit,
                          "sha256": c.sha256, "new": c.new}, indent=2))
        _github_output({"new": str(c.new).lower(), "version": c.version, "pinned": c.pinned,
                        "commit": c.commit, "sha256": c.sha256})
        return 0

    changed = bump(args.version, args.commit, args.sha256)
    print("updated: " + (", ".join(changed) or "nothing (already pinned)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
