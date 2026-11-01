"""The weekly ani-cli watch: finding a newer ani-cli and rewriting the pin."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import setup
from tools import ani_cli_watch as watch

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "a" * 40
SHA = "b" * 64


def fake_git(commit=COMMIT, code=0):
    def run(cmd, **_kw):
        assert cmd[:2] == ["git", "ls-remote"] and cmd[-1] == "refs/heads/master"
        return SimpleNamespace(returncode=code, stdout=f"{commit}\trefs/heads/master\n" if code == 0 else "", stderr="nope")
    return run


def test_check_reads_the_script_at_master_by_commit():
    script = b'#!/bin/sh\nversion_number="99.0.1"\n'
    urls = []

    def fetch(url):
        urls.append(url)
        return script

    c = watch.check(fetch=fetch, run=fake_git())
    assert urls == [setup.ANI_CLI_RAW.format(ref=COMMIT)]
    assert (c.version, c.commit, c.sha256, c.pinned) == ("99.0.1", COMMIT, hashlib.sha256(script).hexdigest(), setup.ANI_CLI_PIN_VERSION)
    assert c.new


def test_same_or_older_version_is_not_new():
    for v in (setup.ANI_CLI_PIN_VERSION, "4.0"):
        c = watch.check(fetch=lambda _u, v=v: f'#!/bin/sh\nversion_number="{v}"\n'.encode(), run=fake_git())
        assert not c.new


@pytest.mark.parametrize("script", [b"<html>not found</html>", b'#!/bin/sh\necho no version\n',
                                    b'#!/bin/sh\nversion_number="5.1.7; rm -rf ~"\n'])
def test_check_rejects_anything_that_isnt_the_script(script):
    with pytest.raises(SystemExit):
        watch.check(fetch=lambda _u: script, run=fake_git())


def test_check_fails_clearly_when_git_fails():
    with pytest.raises(SystemExit, match="master"):
        watch.check(fetch=lambda _u: b"", run=fake_git(code=128))
    with pytest.raises(SystemExit):
        watch.check(fetch=lambda _u: b"", run=fake_git(commit="not-a-sha"))


def test_bump_rewrites_every_pin(tmp_path):
    for rel in ("core/setup.py", ".github/workflows/tests.yml", "README.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)

    changed = watch.bump("5.1.7", COMMIT, SHA, root=tmp_path)
    assert sorted(changed) == [".github/workflows/tests.yml", "README.md", "core/setup.py"]

    code = (tmp_path / "core/setup.py").read_text()
    assert f'ANI_CLI_PIN_VERSION = "5.1.7"' in code
    assert f'ANI_CLI_PIN_COMMIT = "{COMMIT}"' in code
    assert f'ANI_CLI_PIN_SHA256 = "{SHA}"' in code
    ci = (tmp_path / ".github/workflows/tests.yml").read_text()
    assert f"ANI_CLI_COMMIT: {COMMIT}" in ci and "# ani-cli 5.1.7, the version" in ci
    assert "tested against ani-cli **5.1.7**" in (tmp_path / "README.md").read_text()

    # Only the pin changed, nothing else in those files.
    before = (ROOT / "core/setup.py").read_text().splitlines()
    after = code.splitlines()
    assert len(before) == len(after)
    assert sum(a != b for a, b in zip(before, after)) == 3

    assert watch.bump("5.1.7", COMMIT, SHA, root=tmp_path) == []   # running twice is harmless


@pytest.mark.parametrize("args", [("5.1.7\nX", COMMIT, SHA), ("5.1.7", "abc", SHA),
                                  ("5.1.7", COMMIT, "Z" * 64), ('5.1.7"; import os', COMMIT, SHA)])
def test_bump_refuses_malformed_values(args, tmp_path):
    with pytest.raises(SystemExit, match="malformed"):
        watch.bump_texts({}, *args)


def test_bumped_setup_still_imports(tmp_path):
    texts = {p: (ROOT / p).read_text() for p in ("core/setup.py", ".github/workflows/tests.yml", "README.md")}
    code = watch.bump_texts(texts, "5.1.7", COMMIT, SHA)["core/setup.py"]
    compile(code, "core/setup.py", "exec")


def test_cli_check_writes_github_outputs(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(watch, "check", lambda: watch.Candidate("5.1.7", COMMIT, SHA, "5.1.6"))
    assert watch.main(["check"]) == 0
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert lines == {"new": "true", "version": "5.1.7", "pinned": "5.1.6", "commit": COMMIT, "sha256": SHA}


def test_workflow_never_runs_new_ani_cli_with_a_write_token():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github/workflows/ani-cli-watch.yml").read_text())
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    assert "permissions" not in jobs["test"] and "permissions" not in jobs["check"]
    for name in ("propose", "report-failure"):
        steps = " ".join(str(s.get("run", "")) for s in jobs[name]["steps"])
        assert "pytest" not in steps and "ani-cli\" -o" not in steps and "pip install" not in steps
    # Values from the check job reach scripts through env, never pasted into the script.
    for job in jobs.values():
        for step in job["steps"]:
            assert "${{" not in str(step.get("run", ""))
