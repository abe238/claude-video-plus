"""v1.5.4 B2: original-language caption preference (upstream PRs #92
yapaybaba + #123 Nicopatron, via the bugsmithd fork audit).

Deterministic fixtures only; live non-English checks are opt-in and
non-gating. The frozen manual-over-ASR selection guard
(test_retrieval_robustness) must keep passing untouched.
"""
from __future__ import annotations

from pathlib import Path

from acquisition import _caption_patterns
from download import _subtitle_candidates, caption_provenance


# --- fetch patterns --------------------------------------------------------


def test_auto_requests_originals_and_drops_the_wildcard():
    patterns = _caption_patterns(("auto",))
    assert patterns == ".*-orig,en,en-US,en-GB"
    assert "en.*" not in patterns  # ~30 auto-translated pulls, observed 429s


def test_default_english_gains_orig_and_loses_wildcard():
    patterns = _caption_patterns(("en",))
    assert patterns.split(",")[0] == "en-orig"
    assert "en.*" not in patterns
    assert {"en", "en-US", "en-GB"} <= set(patterns.split(","))


def test_regional_english_requests_regional_and_base_orig():
    parts = _caption_patterns(("en-US",)).split(",")
    assert parts[0] == "en-US-orig"
    assert "en-orig" in parts
    assert "en-US" in parts


def test_non_english_language_gains_orig_and_keeps_wildcard():
    parts = _caption_patterns(("es",)).split(",")
    assert parts == ["es-orig", "es.*"]


def test_multi_language_order_is_preserved():
    parts = _caption_patterns(("es", "en")).split(",")
    assert parts.index("es-orig") < parts.index("en-orig")


# --- selection ordering ----------------------------------------------------


def _mk(out_dir: Path, *names: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (out_dir / name).write_text("WEBVTT\n", encoding="utf-8")


def test_auto_prefers_orig_track_over_translation(tmp_path):
    _mk(tmp_path, "video.en.vtt", "video.ja-orig.vtt")
    ordered = _subtitle_candidates(tmp_path, ("auto",))
    assert ordered[0].name == "video.ja-orig.vtt"


def test_auto_production_state_orders_orig_over_translation(tmp_path):
    # The state a production auto fetch can actually produce: the -orig
    # original plus English tracks (the auto pattern never requests a native
    # manual track — manual-over-ASR is therefore a DEFAULT/EXPLICIT-language
    # guarantee, not an auto-mode one; the defensive metadata ranking still
    # orders a manual native track first if one is ever present, e.g. a
    # user-populated directory).
    import json as _json

    _mk(tmp_path, "video.ko-orig.vtt", "video.en.vtt")
    (tmp_path / "video.info.json").write_text(
        _json.dumps({"language": "ko", "subtitles": {},
                     "automatic_captions": {"ko-orig": [], "en": []}}),
        encoding="utf-8",
    )
    ordered = _subtitle_candidates(tmp_path, ("auto",))
    assert [c.name for c in ordered] == ["video.ko-orig.vtt", "video.en.vtt"]


def test_auto_fails_open_without_info_json(tmp_path):
    _mk(tmp_path, "video.en.vtt", "video.ja-orig.vtt")
    ordered = _subtitle_candidates(tmp_path, ("auto",))
    assert ordered[0].name == "video.ja-orig.vtt"  # -orig-first fallback


def test_explicit_language_still_prefers_exact_manual_over_orig(tmp_path):
    # The frozen retrieval guard: a human-written exact track beats the ASR
    # -orig track for the SAME language (ASR garbles proper nouns).
    _mk(tmp_path, "video.en-orig.vtt", "video.en.vtt")
    ordered = _subtitle_candidates(tmp_path, ("en",))
    assert ordered[0].name == "video.en.vtt"
    assert ordered[1].name == "video.en-orig.vtt"


def test_same_language_orig_beats_unrelated_translation(tmp_path):
    _mk(tmp_path, "video.en-orig.vtt", "video.fr.vtt")
    ordered = _subtitle_candidates(tmp_path, ("en",))
    assert ordered[0].name == "video.en-orig.vtt"


# --- provenance ------------------------------------------------------------


def test_provenance_manual_original():
    info = {"subtitles": {"en": []}, "automatic_captions": {}, "language": "en"}
    track = caption_provenance("video.en.vtt", info)
    assert track == {"code": "en", "kind": "manual", "original": True, "translated": False}


def test_provenance_auto_translated():
    info = {"subtitles": {}, "automatic_captions": {"en": []}, "language": "ja"}
    track = caption_provenance("video.en.vtt", info)
    assert track["kind"] == "automatic"
    assert track["translated"] is True
    assert track["original"] is False


def test_provenance_orig_asr_is_original_not_translated():
    info = {"subtitles": {}, "automatic_captions": {"ja-orig": []}, "language": "ja"}
    track = caption_provenance("video.ja-orig.vtt", info)
    assert track["original"] is True
    assert track["translated"] is False


def test_provenance_unknown_when_info_missing():
    track = caption_provenance("video.en.vtt", None)
    assert track["kind"] == "unknown"
    assert track["translated"] is False
    assert track["original"] is False


def test_provenance_never_trusts_filename_orig_alone():
    # A `-orig` suffix on a track the info.json cannot vouch for earns no
    # `original` claim.
    track = caption_provenance("video.xx-orig.vtt", {"subtitles": {}, "automatic_captions": {}})
    assert track["kind"] == "unknown"
    assert track["original"] is False


def test_provenance_manual_translation_is_translated():
    info = {"subtitles": {"en": []}, "automatic_captions": {}, "language": "ja"}
    track = caption_provenance("video.en.vtt", info)
    assert track["kind"] == "manual"
    assert track["translated"] is True
    assert track["original"] is False


def test_provenance_rejects_non_language_shaped_codes():
    info = {"subtitles": {}, "automatic_captions": {}}
    track = caption_provenance("video.<script>alert(1)</script>.vtt", info)
    assert track["code"] == "unknown"


def test_double_acquisition_keeps_first_pass_provenance(cut_clip, monkeypatch, capsys, tmp_path):
    """The media download overwrites `dl` with an acquisition whose info can
    describe a DIFFERENT track; the report must describe the track the
    transcript actually consumed (captured at parse time, first pass)."""
    import sys as _sys

    import watch

    first_vtt = tmp_path / "video.ko-orig.vtt"
    first_vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n감사합니다\n", encoding="utf-8"
    )
    info_first = {
        "language": "ko",
        "caption_codes": {"manual": [], "automatic": ["ko-orig", "en"]},
        "title": "t",
    }
    info_second = {
        "language": "ko",
        "caption_codes": {"manual": ["en"], "automatic": []},
        "title": "t",
    }
    second_vtt = tmp_path / "video.en.vtt"
    second_vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nthank you\n", encoding="utf-8"
    )

    def fake_fetch_captions(source, out_dir):
        return {"subtitle_path": str(first_vtt), "info": info_first,
                "downloaded": False, "selected_strategy": "default", "attempts": []}

    def fake_download(source, out_dir, **kwargs):
        return {"subtitle_path": str(second_vtt), "info": info_second,
                "video_path": str(cut_clip), "downloaded": True,
                "selected_strategy": "default", "attempts": []}

    monkeypatch.setattr(watch, "fetch_captions", fake_fetch_captions)
    monkeypatch.setattr(watch, "download", fake_download)
    monkeypatch.setattr(
        _sys, "argv",
        ["watch.py", "https://www.youtube.com/watch?v=snapshot-test", "--detail", "efficient"],
    )
    rc = watch.main()
    out = capsys.readouterr().out
    assert rc == 0
    # First-pass track, first-pass info: automatic original — never the second
    # acquisition's manual-en description.
    assert "**Caption track:** ko-orig (automatic, original language)" in out


def test_regional_casing_survives_validate_languages(tmp_path):
    # validate_languages lowercases; yt-dlp track codes are BCP-47-cased. The
    # production path (validate → build command) must emit en-US-orig intact.
    from acquisition import build_yt_dlp_command, validate_languages

    languages = validate_languages("en-US")
    assert languages == ("en-us",)  # normalized storage...
    cmd = build_yt_dlp_command(
        "https://www.youtube.com/watch?v=x",
        str(tmp_path / "video.%(ext)s"),
        audio_only=False, captions_only=True,
        languages=languages, cookie_spec=None,
    )
    parts = cmd[cmd.index("--sub-langs") + 1].split(",")
    assert parts[0] == "en-US-orig"  # ...but BCP-47 casing on the wire
    assert "en-orig" in parts


def test_auto_missing_language_never_ranks_manual_translation_first(tmp_path):
    import json as _json

    _mk(tmp_path, "video.en.vtt", "video.ko-orig.vtt")
    (tmp_path / "video.info.json").write_text(
        _json.dumps({"subtitles": {"en": []}, "automatic_captions": {"ko-orig": []}}),
        encoding="utf-8",
    )  # captions present, language ABSENT: en may be a translation
    ordered = _subtitle_candidates(tmp_path, ("auto",))
    assert ordered[0].name == "video.ko-orig.vtt"


def test_auto_non_object_info_root_fails_open(tmp_path):
    _mk(tmp_path, "video.en.vtt", "video.ja-orig.vtt")
    (tmp_path / "video.info.json").write_text("[]", encoding="utf-8")
    ordered = _subtitle_candidates(tmp_path, ("auto",))
    assert ordered[0].name == "video.ja-orig.vtt"  # no AttributeError, -orig first


def test_compound_bcp47_tag_casing(tmp_path):
    from acquisition import build_yt_dlp_command, validate_languages

    languages = validate_languages("zh-Hant-TW")
    cmd = build_yt_dlp_command(
        "https://www.youtube.com/watch?v=x",
        str(tmp_path / "video.%(ext)s"),
        audio_only=False, captions_only=True,
        languages=languages, cookie_spec=None,
    )
    parts = cmd[cmd.index("--sub-langs") + 1].split(",")
    assert parts[0] == "zh-Hant-TW-orig"  # script Title, region UPPER
    assert "zh-orig" in parts


def test_explicit_regional_orig_ranks_before_unrelated_tracks(tmp_path):
    _mk(tmp_path, "video.aa.vtt", "video.en-US-orig.vtt")
    ordered = _subtitle_candidates(tmp_path, ("en-us",))
    assert ordered[0].name == "video.en-US-orig.vtt"
