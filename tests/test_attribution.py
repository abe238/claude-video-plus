"""Focused P04 checks for gratitude, provenance, and derivative authorship."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROVENANCE = (ROOT / "docs/execution/v1/PROVENANCE.md").read_text(encoding="utf-8")
PAGE = (ROOT / "docs/index.html").read_text(encoding="utf-8")


def test_upstream_credit_is_prominent_and_appreciative():
    for text in (README, PAGE):
        assert "Brad Bonanno" in text
        assert "bradautomates/claude-video" in text
    assert "grateful" in README.lower()
    assert "MIT" in README
    assert (ROOT / "LICENSE").is_file()


def test_derivative_identity_does_not_overwrite_upstream_authorship():
    assert "Abe Diaz" in README
    assert "Original work © Brad Bonanno; derivative changes © Abe Diaz." in README
    assert "Abe Diaz / `abe238/claude-video-plus`" in PROVENANCE
    assert "Brad Bonanno / `bradautomates/claude-video@83da59f`" in PROVENANCE


def test_every_named_design_source_has_user_and_repo_credit():
    sources = (
        "taeloautomates/claude-video", "thedirektor/claude-video",
        "RadoslavSheytanov/claude-video", "Tigertycoon/claude-video",
        "manojbadam/claude-video", "CJNA/claude-video",
        "sciencemj/claude-video-local", "troyshelton/claude-video",
        "jsstn/claude-video", "joweiser/claude-video",
        "JoseBallestas/claude-video", "danielfrey63/claude-video",
        "finnvoor/yap", "DanielZYoffe/claude-video-lite",
        "miguelrios/unc-skills",
    )
    for source in sources:
        assert source in README, source
        assert source in PROVENANCE, source


def test_provenance_separates_concepts_from_copied_code():
    assert "No source code from the concept-reference forks" in PROVENANCE
    assert "exact source URL, revision, files, license, modifications, and notices" in PROVENANCE
    assert "No credit here implies that code was copied" in PAGE
