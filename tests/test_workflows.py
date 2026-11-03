"""The release automation: a new version on main publishes itself; signing stays manual."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    data = yaml.safe_load((WF / name).read_text())
    data["on"] = data.pop(True, data.get("on"))   # YAML reads the key `on` as True
    return data


def test_auto_release_runs_on_main_and_calls_the_release_build():
    wf = load("auto-release.yml")
    assert wf["on"] == {"push": {"branches": ["main"]}}
    assert wf["permissions"] == {"contents": "read"}
    release = wf["jobs"]["release"]
    assert release["uses"] == "./.github/workflows/release.yml"
    assert release["with"] == {"tag": "${{ needs.check.outputs.tag }}"}
    assert release["permissions"] == {"contents": "write"} and release["if"] == "needs.check.outputs.tag != ''"
    check = " ".join(str(s.get("run", "")) for s in wf["jobs"]["check"]["steps"])
    assert "already released" in check and "gh release view" in check and "refs/tags/v$version" in check


def test_release_workflow_publishes_for_a_tag_or_a_call():
    wf = load("release.yml")
    assert wf["on"]["workflow_call"]["inputs"]["tag"]["required"] is True
    assert "main" not in wf["on"]["push"]["branches"]               # main releases go through auto-release
    job = wf["jobs"]["build"]
    assert "inputs.tag" in job["env"]["RELEASE_TAG"] and "github.ref_name" in job["env"]["RELEASE_TAG"]
    publish = next(s for s in job["steps"] if s.get("name") == "Publish GitHub Release")
    assert publish["if"] == "env.RELEASE_TAG != ''"
    assert '--target "$GITHUB_SHA"' in publish["run"] and "GITHUB_REF_NAME" not in publish["run"]
    version = next(s for s in job["steps"] if s.get("id") == "v")
    assert "RELEASE_TAG" in version["run"] and "does not match" in version["run"]


def test_nothing_in_ci_can_sign():
    """The signing key never leaves the publisher's Mac: no workflow mentions it."""
    for path in WF.glob("*.yml"):
        text = path.read_text()
        assert "--signer-" not in text and "AniGUI release signing key" not in text, path.name
        assert "secrets." not in text, path.name                 # no stored secret could be a key


def test_existing_release_gets_its_notes_from_the_changelog():
    wf = load("auto-release.yml")
    notes = wf["jobs"]["notes"]
    assert notes["needs"] == "check" and notes["if"] == "needs.check.outputs.released != ''"
    assert notes["permissions"] == {"contents": "write"}
    run = " ".join(str(s.get("run", "")) for s in notes["steps"])
    assert "tools/release_notes.py" in run and "gh release edit" in run and "--notes-file notes.md" in run
    release = load("release.yml")["jobs"]["build"]
    publish = next(s for s in release["steps"] if s.get("name") == "Publish GitHub Release")
    assert "tools/release_notes.py" in publish["run"]         # the same text, made the same way


def test_release_notes_for_the_current_version():
    import sys
    sys.path.insert(0, str(WF.parent.parent))
    from core import __version__, changelog
    from tools.release_notes import notes

    text = notes(__version__)
    assert text.startswith("## What's new\n\n- **")
    for change in changelog.RELEASES[0].changes:
        assert f"- **{change.title}:** {change.text}" in text
    assert f"AniGUI-{__version__}-macOS-AppleSilicon.dmg" in text and "{{VERSION}}" not in text


def test_whats_new_is_written_for_users():
    """Internal fixes (the publisher's tools, the build, logs) are just 'Minor fixes'."""
    import sys
    sys.path.insert(0, str(WF.parent.parent))
    from core import changelog

    internal = ("publisher's mac", "launchagent", "launch constraint", "crash report", "signer", "the log")
    for release in changelog.RELEASES:
        for change in release.changes:
            words = f"{change.title} {change.text}".lower()
            assert not any(w in words for w in internal), (release.version, change.title)
