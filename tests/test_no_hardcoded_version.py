"""Public docs must not hardcode the release version or the test count.

Every release used to cost a docs commit: bump the version in README.md, bump it
again in docs/index.html, re-count the tests, push. The numbers drifted anyway
(README sat at v1.0.3 / "338 tests" while the site said 1.0.5 / 351).

They are now read live — shields.io badges in README, the GitHub API in
docs/index.html — so there is nothing to bump. This test keeps it that way.

Per-release prose belongs in CHANGELOG.md, which is exempt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Files that must stay version-free. CHANGELOG.md and docs/benchmarks/** are
# exempt: a changelog and a dated benchmark are *supposed* to name versions.
GUARDED = ["README.md", "docs/index.html", "docs/watch-videos-with-claude.html"]

SEMVER = re.compile(r"\bv?\d+\.\d+\.\d+\b")
TEST_COUNT = re.compile(r"\b\d{3,}\s+(?:local\s+)?(?:deterministic\s+)?tests?\b", re.I)

# Shields/badge URLs legitimately contain the repo name and query params but no
# pinned version; a literal version inside a badge URL would defeat the point.
ALLOWED_LINES = (
    "img.shields.io",  # live badges
)


def _offending_lines(path: Path, pattern: re.Pattern) -> list[str]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(tok in line for tok in ALLOWED_LINES):
            continue
        if pattern.search(line):
            out.append(f"{path.name}:{i}: {line.strip()[:110]}")
    return out


@pytest.mark.parametrize("rel", GUARDED)
def test_no_hardcoded_release_version(rel):
    hits = _offending_lines(ROOT / rel, SEMVER)
    assert not hits, (
        "hardcoded version in a live-updating doc — the release version is read "
        "from the GitHub API (docs) / shields.io (README). Put per-release prose "
        "in CHANGELOG.md instead:\n  " + "\n  ".join(hits)
    )


@pytest.mark.parametrize("rel", GUARDED)
def test_no_hardcoded_test_count(rel):
    hits = _offending_lines(ROOT / rel, TEST_COUNT)
    assert not hits, (
        "hardcoded test count — CI status is read live; do not pin a number:\n  "
        + "\n  ".join(hits)
    )


def test_the_live_hooks_are_actually_present():
    """Guard the guard: if the dynamic hooks are deleted, the docs would pass the
    checks above by simply saying nothing at all."""
    index = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    assert 'data-gh="version"' in index
    assert 'data-gh="tests"' in index
    assert "api.github.com" in index

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "img.shields.io/github/v/release" in readme
    assert "img.shields.io/github/actions/workflow/status" in readme
