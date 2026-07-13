"""Rolling-caption overlap must be stripped on the shared parse path, not just
in evidence mode.

YouTube auto-captions re-emit the previous cue's tail as the next cue's head.
`_dedupe` only caught exact repeats and prefix-growth (`cur.startswith(prev)`),
so the rolling window fell through and every non-evidence mode (transcript,
efficient, balanced, token-burner) carried the duplicated words into context.
"""
from __future__ import annotations

import transcribe


# Verbatim cue shape from a real YouTube auto-caption track: each cue opens with
# the previous cue's closing words.
ROLLING_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
You're about to get a free meeting notetaker that transcribes right on your

00:00:03.000 --> 00:00:05.000
notetaker that transcribes right on your computer, keeps your data safe that you

00:00:05.000 --> 00:00:07.000
computer, keeps your data safe that you can edit, and it's free.
"""


def _write(tmp_path, body):
    path = tmp_path / "sub.vtt"
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_vtt_strips_rolling_overlap(tmp_path):
    # Cue 2 is fully redundant: cue 1 supplies its head, cue 3 supplies its
    # tail. Dropping it loses no words, so the keeper absorbs its time range.
    segments = transcribe.parse_vtt(str(_write(tmp_path, ROLLING_VTT)))
    assert [s["text"] for s in segments] == [
        "You're about to get a free meeting notetaker that transcribes right on your",
        "computer, keeps your data safe that you can edit, and it's free.",
    ]
    assert segments[0]["end"] == 5.0  # dropped cue extends the keeper


def test_no_spoken_words_are_lost(tmp_path):
    """The collapsed transcript must still contain every distinct phrase."""
    text = " ".join(
        s["text"] for s in transcribe.parse_vtt(str(_write(tmp_path, ROLLING_VTT)))
    )
    for phrase in (
        "You're about to get a free meeting",
        "notetaker that transcribes right on your",
        "computer, keeps your data safe that you",
        "can edit, and it's free.",
    ):
        assert phrase in text


def test_rendered_transcript_has_no_repeated_tail(tmp_path):
    text = transcribe.format_transcript(
        transcribe.parse_vtt(str(_write(tmp_path, ROLLING_VTT)))
    )
    # The duplicated span must appear exactly once in the rendered transcript.
    assert text.count("notetaker that transcribes right on your") == 1
    assert text.count("computer, keeps your data safe that you") == 1


def test_manual_captions_are_untouched(tmp_path):
    """Human-authored subtitles have no rolling overlap; the pass must no-op."""
    manual = """WEBVTT

00:00:01.000 --> 00:00:03.000
The quick brown fox.

00:00:03.000 --> 00:00:05.000
Jumps over the lazy dog.
"""
    segments = transcribe.parse_vtt(str(_write(tmp_path, manual)))
    assert [s["text"] for s in segments] == [
        "The quick brown fox.",
        "Jumps over the lazy dog.",
    ]


def test_dedupe_rolling_is_idempotent():
    """evidence.py calls dedupe_rolling on already-parsed segments; applying it
    at parse time must not corrupt the second application."""
    segments = [
        {"start": 0.0, "end": 3.0, "text": "alpha bravo charlie delta golf hotel india"},
        {"start": 3.0, "end": 6.0, "text": "golf hotel india juliet kilo lima mike"},
    ]
    once = transcribe.dedupe_rolling(segments)
    twice = transcribe.dedupe_rolling(once)
    assert once == twice
