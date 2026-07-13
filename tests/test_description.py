"""The author-supplied description is evidence, and it is untrusted.

Measured on youtube QacqRZ0vsD4 ("top GitHub repos of the week"): the auto-caption
transcript recovers 1 of the 13 repo names the video is *about* — ASR renders them
"Omniroot", "stricks", "Codeex Bar". The description carries all 13 verbatim in
~540 tokens. Ignoring it was a correctness hole, not just a cost one.

It is also author-controlled text, so it is bounded, labeled, and never
authoritative for what happens in the video.
"""
from __future__ import annotations

import download


def test_description_is_returned_bounded():
    info = {"description": "x" * 5000}
    out = download.format_description(info, limit=2000)
    assert out is not None
    assert len(out) < 2200  # bounded payload, not the raw 5000
    assert "truncated" in out.lower(), "a clipped description must say so"


def test_short_description_is_untouched():
    body = "Repos featured:\nbradautomates/claude-video\nusestrix/strix"
    out = download.format_description({"description": body}, limit=2000)
    assert body in out
    assert "truncated" not in out.lower()


def test_missing_or_blank_description_yields_none():
    assert download.format_description({}) is None
    assert download.format_description({"description": ""}) is None
    assert download.format_description({"description": "   \n  "}) is None


def test_real_shape_preserves_exact_repo_names():
    """The whole point: proper nouns ASR cannot produce must survive verbatim."""
    body = (
        "Repos featured:\n"
        "diegosouzapw/OmniRoute\n"
        "steipete/CodexBar\n"
        "bradautomates/claude-video\n"
    )
    out = download.format_description({"description": body}, limit=2000)
    for repo in ("diegosouzapw/OmniRoute", "steipete/CodexBar", "bradautomates/claude-video"):
        assert repo in out
