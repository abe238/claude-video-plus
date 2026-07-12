"""Focused P04 checks for canonical release metadata and public claims."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _skill_version():
    text = (ROOT / "skills/watch/SKILL.md").read_text(encoding="utf-8")
    return re.search(r'^\s*version: ["\']?([^"\'\n]+)', text, re.MULTILINE).group(1)


def test_release_versions_and_identity_are_canonical():
    claude = _json(".claude-plugin/plugin.json")
    codex = _json(".codex-plugin/plugin.json")
    assert {_skill_version(), claude["version"], codex["version"]} == {"0.3.0"}
    assert claude["repository"] == codex["repository"] == "https://github.com/abe238/claude-video-plus"
    assert claude["homepage"] == codex["homepage"] == "https://abe238.github.io/claude-video-plus/"
    assert claude["license"] == codex["license"] == "MIT"


def test_public_numeric_claims_state_population_and_limits():
    public = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/index.html", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
    ).lower()
    assert "one-video" in public or "one video" in public
    assert "three-question" in public or "three questions" in public
    assert "broader testing is in progress" in public
    assert "docs/benchmarks" in public


def test_ci_and_release_workflows_cover_push_and_artifact():
    tests = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s*push:\s*$", tests)
    assert re.search(r"(?m)^\s*pull_request:\s*$", tests)
    assert "python -m pytest -q" in tests
    assert "build-skill.sh" in release
    assert "watch.skill" in release


def test_changelog_distinguishes_unreleased_derivative_from_upstream():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.3.0] — Unreleased" in text
    assert "There is no `v0.3.0` tag or release artifact yet" in text
    assert "## [0.2.0] — 2026-06-30 (upstream)" in text
