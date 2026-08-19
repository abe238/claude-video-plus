"""v1.5.4 B1: whisper repetition-loop defense (idea from the bugsmithd fork
audit; detector + per-attempt/receipt-read wiring rebuilt for this pipeline).

Calibration contract: the documented real failure (one line 6,434x) and its
variants MUST trip; legitimate repetition (chorus, chant under threshold,
call-and-response, meditation, non-speech markers, credits) MUST NOT.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import whisper
from transcription import TranscriptionRequest
from transcription_adapters import CloudWhisperAdapter, _run_chunked
from transcription_chunks import (
    LOOP_MIN_CONSECUTIVE,
    AudioChunk,
    ChunkReceiptStore,
    PreparedAudio,
    detect_repetition_loop,
)


def _segs(texts, start=0.0, step=1.0):
    return [
        {"start": round(start + i * step, 2), "end": round(start + (i + 1) * step, 2), "text": t}
        for i, t in enumerate(texts)
    ]


# --- calibration: positives ------------------------------------------------


def test_documented_failure_6434_consecutive_repeats_trips():
    looped = _segs(["Thanks for watching."] * 6434)
    reason = detect_repetition_loop(looped)
    assert reason and "consecutively" in reason


def test_intra_segment_giant_repeat_trips():
    # Punctuated: the sentence stream flattens one giant segment into 300
    # identical sentences (same failure shape as 300 segments).
    punctuated = _segs(["I'm sorry. " * 300])
    reason = detect_repetition_loop(punctuated)
    assert reason and "consecutively" in reason
    # Punctuation-less: no sentence boundaries to split on — the word-period
    # scan must catch it inside the single segment.
    bare = _segs(["im so sorry " * 100])
    reason = detect_repetition_loop(bare)
    assert reason and "single segment" in reason


def test_japanese_single_segment_packed_loop_trips():
    # The review's exact case: ありがとう。 repeated thousands of times inside
    # ONE segment, with no spaces — CJK sentence enders split it.
    reason = detect_repetition_loop(_segs(["ありがとう。" * 6434]))
    assert reason and "consecutively" in reason


def test_varying_group_packing_still_trips():
    # 270 repeats packed into 45 segments in varying 5/6/7-sentence groups:
    # per-segment counting misses it, the flattened stream does not.
    import itertools

    sizes = itertools.cycle([5, 6, 7])
    texts = ["I will not do that again. " * next(sizes) for _ in range(45)]
    reason = detect_repetition_loop(_segs(texts))
    assert reason and "consecutively" in reason


def test_scattered_dominance_trips():
    # 88 of 100 stream lines are one sentence (7 loop lines per unique
    # filler), interleaved so no consecutive run reaches the threshold.
    texts = []
    fillers = iter(f"unique filler line {i}" for i in range(1000))
    for _ in range(30):
        texts.extend(["the loop line"] * 7)
        texts.append(next(fillers))
    reason = detect_repetition_loop(_segs(texts[:100]))
    assert reason and "of the chunk" in reason


def test_punctuation_and_case_do_not_hide_a_loop():
    looped = _segs(["Thanks for watching!", "thanks for watching", "THANKS FOR WATCHING."] * 20)
    assert detect_repetition_loop(looped) is not None


# --- calibration: negatives ------------------------------------------------


def test_chorus_repeated_8x_does_not_trip():
    verse = [f"verse line {i}" for i in range(8)]
    chorus = ["na na na hey hey goodbye"] * 8
    assert detect_repetition_loop(_segs(verse + chorus + verse)) is None


def test_consecutive_boundary_one_under_threshold():
    # Boundary check by construction (deliberately threshold-derived): one
    # repeat under the limit must not trip.
    chant = ["om namah shivaya"] * (LOOP_MIN_CONSECUTIVE - 1)
    assert detect_repetition_loop(_segs(chant)) is None


def test_realistic_three_minute_kirtan_does_not_trip():
    # Threshold-independent, duration-realistic negative: whisper renders live
    # chant as merged multi-repeat segments with varying counts, ~60 segments
    # across a 3-minute chunk. Known ceiling (documented, escape hatch): a
    # transcript of PERFECTLY identical single-mantra segments can trip.
    base = "hare krishna hare krishna krishna krishna hare hare"
    texts = [(base + " ") * (1 + (i % 3)) for i in range(60)]
    assert detect_repetition_loop(_segs(texts)) is None


def test_call_and_response_does_not_trip():
    pair = ["hallelujah", "praise the lord"]
    assert detect_repetition_loop(_segs(pair * 40)) is None


def test_meditation_short_runs_do_not_trip():
    texts = (["breathe in"] * 10 + ["breathe out"] * 10) * 3
    assert detect_repetition_loop(_segs(texts)) is None


def test_non_speech_markers_are_excluded():
    markers = _segs(["[Applause]"] * 50 + ["(music)"] * 50 + ["♪ ♪ ♪"] * 50)
    assert detect_repetition_loop(markers) is None


def test_credits_unique_lines_do_not_trip():
    credits = _segs([f"role {i}: person {i}" for i in range(60)])
    assert detect_repetition_loop(credits) is None


def test_empty_segments_do_not_trip():
    assert detect_repetition_loop([]) is None
    assert detect_repetition_loop(_segs(["", "  ", ""])) is None


# --- wiring: attempts, receipts, escape hatch, ledger ----------------------


LOOPED = [{"start": float(i), "end": float(i + 1), "text": "stuck line"} for i in range(25)]
CLEAN = [{"start": 0.0, "end": 1.0, "text": "a normal sentence"}]


def _request(tmp_path: Path, **values) -> TranscriptionRequest:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"a" * 50)
    chunk = AudioChunk(index=0, path=audio, source_offset=10.0, duration=5.0, sha256="abc")
    defaults = {
        "media_path": media,
        "work_dir": tmp_path / "work",
        "adapter_order": (),
        "allow_remote": True,
        "config": {"receipts": True},
        "prepared_audio": PreparedAudio(audio, (chunk,), 10.0, 15.0),
    }
    defaults.update(values)
    return TranscriptionRequest(**defaults)


def test_looped_attempts_fail_the_chunk_and_never_cache(tmp_path):
    request = _request(tmp_path)
    store_path = tmp_path / "receipts.json"
    store = ChunkReceiptStore(store_path, enabled=True)
    result = _run_chunked(
        request, store, adapter="stub", model="m",
        transcribe_one=lambda chunk: list(LOOPED), remote=False,
    )
    assert result.state == "unavailable"
    assert result.diagnostics["loop_detected_chunks"] == 1
    assert any("repetition loop" in w for w in result.warnings)
    persisted = json.loads(store_path.read_text()) if store_path.exists() else {"entries": {}}
    assert persisted["entries"] == {}  # a loop is never stored


def test_retry_recovers_from_a_looped_first_attempt(tmp_path):
    request = _request(tmp_path)
    outputs = [list(LOOPED), list(CLEAN)]
    result = _run_chunked(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False),
        adapter="stub", model="m",
        transcribe_one=lambda chunk: outputs.pop(0), remote=False,
    )
    assert result.state == "success"
    assert result.segments[0].text == "a normal sentence"
    # Absolute timestamps still shifted by the chunk's source offset.
    assert result.segments[0].start == 10.0
    assert any("attempt discarded (loop" in w for w in result.warnings)
    # A RECOVERED loop still counts: the diagnostic reports detections, not
    # only chunks that ultimately failed.
    assert result.diagnostics["loop_detected_chunks"] == 1


def test_detector_off_receipts_live_in_a_separate_namespace(tmp_path):
    """Two-phase: a WATCH_LOOP_DETECT=0 run stores its looped receipt under
    the loop0 policy key, so the next ENABLED run cannot even see it — a
    clean cache miss, never a poisoned reuse."""
    off = _request(tmp_path, config={"receipts": True, "loop_detect": False})
    store_path = tmp_path / "receipts.json"
    store = ChunkReceiptStore(store_path, enabled=True)
    result_off = _run_chunked(
        off, store, adapter="stub", model="m",
        transcribe_one=lambda chunk: list(LOOPED), remote=False,
    )
    assert result_off.state == "success"  # escape hatch accepted the loop
    assert result_off.diagnostics["loop_detected_chunks"] == 0
    store.flush()
    assert json.loads(store_path.read_text())["entries"]  # stored under loop0

    on = _request(tmp_path, config={"receipts": True, "loop_detect": True})
    store2 = ChunkReceiptStore(store_path, enabled=True)
    result_on = _run_chunked(
        on, store2, adapter="stub", model="m",
        transcribe_one=lambda chunk: list(CLEAN), remote=False,
    )
    assert result_on.state == "success"
    assert result_on.segments[0].text == "a normal sentence"
    assert result_on.diagnostics["reused_chunks"] == 0  # loop0 entry invisible


def test_looped_receipt_in_enabled_namespace_is_discarded_at_read(tmp_path):
    """Belt-and-braces: even a looped payload that somehow landed under the
    ENABLED policy key is revalidated and discarded on read."""
    request = _request(tmp_path, config={"receipts": True, "loop_detect": True})
    store_path = tmp_path / "receipts.json"
    store = ChunkReceiptStore(store_path, enabled=True)
    [chunk] = request.prepared_audio.chunks
    store.put("stub", "m", request.language, chunk, list(LOOPED), "loop1")
    store.flush()
    result = _run_chunked(
        request, ChunkReceiptStore(store_path, enabled=True),
        adapter="stub", model="m",
        transcribe_one=lambda chunk: list(CLEAN), remote=False,
    )
    assert result.state == "success"
    assert result.segments[0].text == "a normal sentence"
    assert any("cached transcript discarded (loop" in w for w in result.warnings)
    assert result.diagnostics["loop_detected_chunks"] == 1
    assert result.diagnostics["reused_chunks"] == 0


def test_escape_hatch_accepts_loops(tmp_path):
    request = _request(tmp_path, config={"receipts": False, "loop_detect": False})
    result = _run_chunked(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False),
        adapter="stub", model="m",
        transcribe_one=lambda chunk: list(LOOPED), remote=False,
    )
    assert result.state == "success"
    assert len(result.segments) == len(LOOPED)


def test_looped_remote_attempts_still_charge_the_ledger(tmp_path, monkeypatch):
    """A1 interaction: a looping remote chunk retries, and every retry's send
    draws from the run's cost budget."""
    request = _request(tmp_path, config={"receipts": False})
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 0

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)
        return list(LOOPED)

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    result = CloudWhisperAdapter("groq").transcribe(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False)
    )
    assert result.state == "unavailable"
    assert result.diagnostics["loop_detected_chunks"] == 1
    assert request.remote_ledger.attempts == request.max_attempts  # every retry paid
    assert result.diagnostics["remote_transmission"] is True


# --- pipeline-level identity union -----------------------------------------


class _NoSidecarAdapter:
    requires_audio = False
    is_remote = False
    name = "sidecar"

    def probe(self, request):
        from transcription import AdapterAvailability

        return AdapterAvailability(False, "no_sidecar")

    def transcribe(self, request, receipts):  # pragma: no cover
        raise AssertionError("unavailable adapter must not transcribe")


class _LoopingLocalAdapter:
    requires_audio = False
    is_remote = False

    def __init__(self, name):
        self.name = name

    def probe(self, request):
        from transcription import AdapterAvailability

        return AdapterAvailability(True)

    def transcribe(self, request, receipts):
        from transcription_adapters import _run_chunked

        return _run_chunked(
            request, receipts, adapter=self.name, model="m",
            transcribe_one=lambda chunk: list(LOOPED), remote=False,
        )


def test_same_chunk_looping_under_two_adapters_counts_once(tmp_path):
    from transcription import TranscriptionPipeline

    request = _request(
        tmp_path, adapter_order=("stub-a", "stub-b"), config={"receipts": False}
    )
    result = TranscriptionPipeline(
        {
            "sidecar": _NoSidecarAdapter(),
            "stub-a": _LoopingLocalAdapter("stub-a"),
            "stub-b": _LoopingLocalAdapter("stub-b"),
        }
    ).run(request)
    # Both adapters looped on the SAME single chunk: identity, not tally —
    # and the all-unavailable terminal path must keep the count.
    assert result.state == "unavailable"
    assert result.diagnostics["loop_detected_chunks"] == 1
    assert result.diagnostics["loop_chunk_indices"] == [0]


def test_pre_policy_receipts_are_invalidated_not_reused(tmp_path):
    """Contract (explicit): receipts written by v1.5.3 and earlier carry keys
    WITHOUT the detector-policy field, so they cannot be addressed by the new
    key and are wholesale invalidated — a clean re-transcription, never a
    reuse of unscreened text."""
    import hashlib as _hashlib

    request = _request(tmp_path, config={"receipts": True, "loop_detect": True})
    [chunk] = request.prepared_audio.chunks
    # Reconstruct the v1.5.3 key shape (no "policy" field).
    old_payload = {
        "schema": 2, "adapter": "stub", "model": "m", "language": request.language,
        "chunk_sha256": chunk.sha256, "source_offset": chunk.source_offset,
        "duration": chunk.duration,
    }
    old_key = _hashlib.sha256(
        json.dumps(old_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    store_path = tmp_path / "receipts.json"
    store_path.write_text(json.dumps({
        "schema_version": 2,
        "entries": {old_key: {"chunk_sha256": chunk.sha256, "segments": LOOPED}},
    }), encoding="utf-8")
    store_path.chmod(0o600)
    result = _run_chunked(
        request, ChunkReceiptStore(store_path, enabled=True),
        adapter="stub", model="m",
        transcribe_one=lambda chunk: list(CLEAN), remote=False,
    )
    assert result.state == "success"
    assert result.segments[0].text == "a normal sentence"
    assert result.diagnostics["reused_chunks"] == 0  # old receipt unreachable


def test_word_timestamps_survive_loop_retry(tmp_path):
    request = _request(tmp_path, config={"receipts": False})
    clean_with_words = [{
        "start": 0.0, "end": 1.0, "text": "a normal sentence",
        "words": [{"word": "a", "start": 0.0, "end": 0.2},
                  {"word": "normal", "start": 0.2, "end": 0.6}],
    }]
    outputs = [list(LOOPED), clean_with_words]
    result = _run_chunked(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False),
        adapter="stub", model="m",
        transcribe_one=lambda chunk: outputs.pop(0), remote=False,
    )
    assert result.state == "success"
    words = result.segments[0].words
    assert [w.word for w in words] == ["a", "normal"]
    assert words[0].start == 10.0  # shifted by the chunk's source offset


def test_loop_diagnostics_state_coverage(tmp_path):
    """Loop identities survive every usable terminal: partial (loops + clean
    in one adapter), degraded (later adapter rescue), and fatal."""
    from transcription import AdapterAvailability, TranscriptionPipeline, TranscriptResult, TranscriptSegment

    # partial: chunk 0 loops and fails; chunk 1 clean.
    media = tmp_path / "clip.mp4"; media.write_bytes(b"m")
    audio0 = tmp_path / "c0.mp3"; audio0.write_bytes(b"a")
    audio1 = tmp_path / "c1.mp3"; audio1.write_bytes(b"b")
    chunks = (
        AudioChunk(index=0, path=audio0, source_offset=0.0, duration=5.0, sha256="x0"),
        AudioChunk(index=1, path=audio1, source_offset=5.0, duration=5.0, sha256="x1"),
    )
    request = TranscriptionRequest(
        media_path=media, work_dir=tmp_path / "w", adapter_order=(),
        config={"receipts": False},
        prepared_audio=PreparedAudio(audio0, chunks, 0.0, 10.0),
    )
    result = _run_chunked(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False),
        adapter="stub", model="m",
        transcribe_one=lambda c: list(LOOPED) if c.index == 0 else list(CLEAN),
        remote=False,
    )
    assert result.state == "partial"
    assert result.diagnostics["loop_detected_chunks"] == 1

    # degraded: adapter A loops out, adapter B rescues — count preserved.
    class _CleanLocal:
        requires_audio = False
        is_remote = False
        name = "clean"

        def probe(self, request):
            return AdapterAvailability(True)

        def transcribe(self, request, receipts):
            return TranscriptResult(
                state="success",
                segments=(TranscriptSegment(start=0.0, end=1.0, text="rescued", adapter="clean"),),
                adapter="clean",
            )

    request2 = _request(tmp_path, adapter_order=("stub-a", "clean"), config={"receipts": False})
    degraded = TranscriptionPipeline(
        {"sidecar": _NoSidecarAdapter(), "stub-a": _LoopingLocalAdapter("stub-a"), "clean": _CleanLocal()}
    ).run(request2)
    assert degraded.state == "degraded"
    assert degraded.diagnostics["loop_detected_chunks"] == 1

    # fatal after loops: count still carried.
    class _FatalLocal:
        requires_audio = False
        is_remote = False
        name = "fatal"

        def probe(self, request):
            return AdapterAvailability(True)

        def transcribe(self, request, receipts):
            return TranscriptResult(state="fatal", failure_code="audio_not_prepared")

    request3 = _request(tmp_path, adapter_order=("stub-a", "fatal"), config={"receipts": False})
    fatal = TranscriptionPipeline(
        {"sidecar": _NoSidecarAdapter(), "stub-a": _LoopingLocalAdapter("stub-a"), "fatal": _FatalLocal()}
    ).run(request3)
    assert fatal.state == "fatal"
    assert fatal.diagnostics["loop_detected_chunks"] == 1
