"""Regression tests for the Ken Robinson evidence-mode retrieval miss.

Root cause (corpus-9 bake-off, iG9CE55wbtY): the pipeline consumed the ASR
caption track (video.en-orig.vtt) instead of the manual track sitting next to
it, and lexical retrieval scored the answer chapter 0.000 because ASR spelled
"Gillian Lynne" as "jillian lynn" ("schools" vs "school" compounding). Fixes:
manual-track preference, suffix normalization, zero-hit fuzzy term matching,
and unmet-term notes in the report.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "watch" / "scripts"))

import evidence as ev  # noqa: E402
from download import _subtitle_candidates  # noqa: E402


# --- S1: manual caption track preferred over the ASR "-orig" track ---------

def _touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_text("WEBVTT\n", encoding="utf-8")


def test_manual_track_beats_asr_orig(tmp_path):
    _touch(tmp_path, "video.en-be.vtt", "video.en-orig.vtt", "video.en.vtt")
    ordered = _subtitle_candidates(tmp_path, ("en",))
    assert ordered[0].name == "video.en.vtt"
    assert ordered[1].name == "video.en-orig.vtt"


def test_asr_orig_still_used_when_only_track(tmp_path):
    _touch(tmp_path, "video.en-orig.vtt", "video.en-da.vtt")
    ordered = _subtitle_candidates(tmp_path, ("en",))
    assert ordered[0].name == "video.en-orig.vtt"


# --- S2: suffix normalization + zero-hit fuzzy matching --------------------

def test_plural_question_matches_singular_transcript():
    spans = [{"text": "the school system was built for industrialism"},
             {"text": "totally unrelated content about music"}]
    scores = ev.score_spans(spans, ["schools"])
    assert scores[0] > 0 and scores[1] == 0


def _mk_segments(chunks):
    """chunks: list of (start, text) -> minimal segment dicts."""
    return [{"start": float(s), "end": float(s) + 4.0, "text": t}
            for s, t in chunks]


def _run_targeted(question, segments, chapters_info, duration=200.0):
    chapters = ev.load_chapters({"chapters": chapters_info}, segments, duration)
    ev.attach_chapters(segments, chapters)
    spans = ev.build_spans(segments, chapters)
    return ev._targeted(question, segments, chapters, spans, 24000, duration), chapters


def test_fuzzy_rescues_asr_spelling():
    """Question says 'Gillian Lynne'; ASR transcript says 'jillian lynn' --
    the answer chapter must still be selected, with a note."""
    segments = _mk_segments([
        (0, "welcome to the talk about education themes"),
        (10, "education and industrialism shaped the modern curriculum"),
        (100, "jillian lynn was taken to a specialist as a child"),
        (110, "jillian could not sit still she was a dancer"),
        (120, "jillian lynn became a famous choreographer"),
    ])
    chapters_info = [
        {"start_time": 0, "end_time": 90, "title": "Education"},
        {"start_time": 90, "end_time": 200, "title": "epiphany"},
    ]
    (evd, blocks, selected, frames, notes), chapters = _run_targeted(
        "What is the Gillian Lynne story?", segments, chapters_info)
    titles = {chapters[c]["title"] for c in selected}
    assert "epiphany" in titles
    assert any("'gillian'" in n and "'jillian'" in n for n in notes)


def test_fuzzy_is_noop_when_exact_term_present():
    segments = _mk_segments([
        (0, "gillian lynne was a dancer"),
        (100, "jillian is a different person entirely"),
    ])
    chapters_info = [
        {"start_time": 0, "end_time": 90, "title": "A"},
        {"start_time": 90, "end_time": 200, "title": "B"},
    ]
    (_, _, _, _, notes), _ = _run_targeted(
        "What is the Gillian story?", segments, chapters_info)
    assert not any("matched transcript spelling" in n for n in notes)


def test_unmet_term_note_when_answer_absent():
    segments = _mk_segments([
        (0, "we talk about cooking pasta today"),
        (100, "and now more about pasta sauces"),
    ])
    chapters_info = [
        {"start_time": 0, "end_time": 90, "title": "A"},
        {"start_time": 90, "end_time": 200, "title": "B"},
    ]
    (_, _, _, _, notes), _ = _run_targeted(
        "What does the speaker say about Kubernetes?", segments, chapters_info)
    assert any("'kubernete" in n and "not found in selected evidence" in n for n in notes)


def test_unmet_note_skips_lowercase_framing_words():
    """'teaching'/'episode'-style framing words fired false alarms on every
    healthy video; only capitalized (name-like) terms warrant the warning."""
    segments = _mk_segments([
        (0, "we talk about cooking pasta today"),
        (100, "and now more about pasta sauces"),
    ])
    chapters_info = [
        {"start_time": 0, "end_time": 90, "title": "A"},
        {"start_time": 90, "end_time": 200, "title": "B"},
    ]
    (_, _, _, _, notes), _ = _run_targeted(
        "What is this video teaching about cooking?", segments, chapters_info)
    assert not any("not found in selected evidence" in n for n in notes)


def test_lev1_matcher_bounds():
    assert ev._lev1("gillian", "jillian")      # substitution
    assert ev._lev1("lynne", "lynn")           # deletion
    assert not ev._lev1("gillian", "william")  # distance 2
    assert not ev._lev1("story", "history")    # length gap 2
