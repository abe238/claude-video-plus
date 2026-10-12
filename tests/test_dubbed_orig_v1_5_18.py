"""Dubbed videos expose one -orig ASR track per audio language; auto must pick
the one matching the video's language (English-first when unknown)."""
from __future__ import annotations

import json

import pytest

from download import _subtitle_candidates, caption_provenance

CODES = ["bn-orig", "de-DE-orig", "en-orig", "es-US-orig", "fr-FR-orig", "hi-orig", "ko-orig"]


def _dir(tmp_path, codes, language):
    for c in codes:
        (tmp_path / f"video.{c}.vtt").write_text("WEBVTT\n")
    info = {"automatic_captions": {c: [] for c in codes}}
    if language:
        info["language"] = language
    (tmp_path / "video.info.json").write_text(json.dumps(info))
    return tmp_path


@pytest.mark.parametrize("language,expected", [
    ("en-US", "en-orig"), ("ko", "ko-orig"), ("de", "de-DE-orig"), (None, "en-orig"),
])
def test_auto_picks_matching_orig(tmp_path, language, expected):
    d = _dir(tmp_path, CODES, language)
    assert _subtitle_candidates(d, ("auto",))[0].name == f"video.{expected}.vtt"


def test_unknown_language_without_en_is_alphabetical(tmp_path):
    d = _dir(tmp_path, ["hi-orig", "bn-orig"], None)
    assert _subtitle_candidates(d, ("auto",))[0].name == "video.bn-orig.vtt"


def test_single_orig_unchanged(tmp_path):
    d = _dir(tmp_path, ["bn-orig"], "en-US")
    assert _subtitle_candidates(d, ("auto",))[0].name == "video.bn-orig.vtt"


def test_provenance_mismatched_orig_not_original(tmp_path):
    info = {"language": "en-US", "automatic_captions": {"bn-orig": []}}
    p = caption_provenance(tmp_path / "video.bn-orig.vtt", info)
    assert p["original"] is False and p["translated"] is True


def test_provenance_matching_and_unknown_orig_still_original(tmp_path):
    ok = caption_provenance(tmp_path / "video.en-orig.vtt",
                            {"language": "en-US", "automatic_captions": {"en-orig": []}})
    assert ok["original"] is True and ok["translated"] is False
    unk = caption_provenance(tmp_path / "video.bn-orig.vtt",
                             {"automatic_captions": {"bn-orig": []}})
    assert unk["original"] is True
