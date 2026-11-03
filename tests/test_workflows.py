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
