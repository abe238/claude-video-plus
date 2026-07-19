"""R2b: word-level timestamps — absent-tolerant words[] on TranscriptSegment,
offset shifting, response parsing, and the receipt schema bump.

Words are best-effort everywhere: a backend that returns none yields segments
with an empty words tuple, never an error (fail-open). Receipts written before
the schema bump carry segment-only payloads that would mask the feature on
resume, so the bump must invalidate them wholesale.
"""
from __future__ import annotations

import json
import subprocess

import pytest

import transcription_adapters as ta
import transcription_chunks as chunks
import whisper
from transcription import TranscriptSegment
from transcription_chunks import AudioChunk, ChunkReceiptStore


# --- TranscriptSegment.words ---------------------------------------------------

def test_words_default_to_empty_tuple():
    segment = TranscriptSegment(start=0.0, end=1.0, text="hi")
    assert segment.words == ()


def test_from_mapping_without_words_is_tolerated():
    segment = TranscriptSegment.from_mapping({"start": 0.0, "end": 1.0, "text": "hi"})
    assert segment.words == ()


def test_from_mapping_shifts_word_timestamps_by_segment_offset():
    segment = TranscriptSegment.from_mapping(
        {
            "start": 1.0,
            "end": 3.0,
            "text": "hello world",
            "words": [
                {"word": "hello", "start": 1.0, "end": 1.8},
                {"word": "world", "start": 2.0, "end": 2.9},
            ],
        },
        offset=10.0,
    )
    assert segment.start == 11.0 and segment.end == 13.0
    assert [(w.word, w.start, w.end) for w in segment.words] == [
        ("hello", 11.0, 11.8),
        ("world", 12.0, 12.9),
    ]


def test_malformed_word_entries_are_dropped_fail_open():
    segment = TranscriptSegment.from_mapping(
        {
            "start": 0.0,
            "end": 2.0,
            "text": "ok",
            "words": [
                {"word": "ok", "start": 0.0, "end": 0.5},
                {"word": "", "start": 0.6, "end": 0.7},        # empty text
                {"start": 1.0, "end": 1.1},                      # no word
                {"word": "bad", "start": "x", "end": 1.4},      # non-numeric
                "not-a-mapping",
            ],
        }
    )
    assert [w.word for w in segment.words] == ["ok"]


def test_words_round_trip_through_to_dict():
    original = TranscriptSegment.from_mapping(
        {
            "start": 0.0,
            "end": 2.0,
            "text": "round trip",
            "words": [
                {"word": "round", "start": 0.0, "end": 0.9},
                {"word": "trip", "start": 1.0, "end": 1.9},
            ],
        }
    )
    restored = TranscriptSegment.from_mapping(original.to_dict())
    assert restored == original
    assert restored.words == original.words


# --- whisper.py: request + response --------------------------------------------

def test_build_multipart_repeats_list_valued_fields(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    body, _boundary = whisper.build_multipart(
        {"timestamp_granularities[]": ["word", "segment"]}, audio
    )
    assert body.count(b'name="timestamp_granularities[]"') == 2
    assert b"word" in body and b"segment" in body


def test_cloud_request_asks_for_word_granularity(monkeypatch, tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    captured = {}
    real_build = whisper.build_multipart

    def spy_build(fields, path):
        captured.update(fields)
        return real_build(fields, path)

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"segments": []}).encode()

    monkeypatch.setattr(whisper, "build_multipart", spy_build)
    monkeypatch.setattr(whisper, "urlopen", lambda *a, **k: _Response())
    whisper._post_whisper("https://example.invalid", "key", "model", audio, max_attempts=1)
    granularities = captured.get("timestamp_granularities[]")
    assert granularities is not None and "word" in granularities


def test_segments_from_response_prefers_nested_words():
    data = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "hi there",
                "words": [
                    {"word": "hi", "start": 0.0, "end": 0.4},
                    {"word": "there", "start": 0.5, "end": 0.9},
                ],
            }
        ]
    }
    out = whisper.segments_from_response(data)
    assert out[0]["words"] == [
        {"word": "hi", "start": 0.0, "end": 0.4},
        {"word": "there", "start": 0.5, "end": 0.9},
    ]


def test_segments_from_response_assigns_top_level_words_by_time():
    data = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "one"},
            {"start": 1.0, "end": 2.0, "text": "two"},
        ],
        "words": [
            {"word": "one", "start": 0.1, "end": 0.5},
            {"word": "two", "start": 1.1, "end": 1.5},
        ],
    }
    out = whisper.segments_from_response(data)
    assert [w["word"] for w in out[0]["words"]] == ["one"]
    assert [w["word"] for w in out[1]["words"]] == ["two"]


def test_segments_from_response_without_words_stays_segment_only():
    out = whisper.segments_from_response(
        {"segments": [{"start": 0.0, "end": 1.0, "text": "plain"}]}
    )
    assert "words" not in out[0]


def test_shift_segments_shifts_nested_words_too():
    shifted = whisper.shift_segments(
        [{"start": 0.0, "end": 1.0, "text": "w",
          "words": [{"word": "w", "start": 0.2, "end": 0.8}]}],
        10.0,
    )
    assert shifted[0]["words"][0] == {"word": "w", "start": 10.2, "end": 10.8}


# --- whisper-cli adapter --------------------------------------------------------

class _Chunk:
    index = 0
    source_offset = 0.0
    duration = 2.0


class _Request:
    language = "auto"
    timeout = 5.0


def test_whisper_cli_parses_words_from_json_output(tmp_path, monkeypatch):
    chunk = _Chunk()
    chunk.path = tmp_path / "chunk_000.wav"
    chunk.path.write_bytes(b"")
    request = _Request()
    request.work_dir = tmp_path

    payload = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.5,
                "text": " spoken words ",
                "words": [
                    {"word": " spoken", "start": 0.0, "end": 0.7},
                    {"word": " words", "start": 0.8, "end": 1.4},
                ],
            }
        ]
    }

    def fake_run(command, **kwargs):
        out_dir = tmp_path / "whisper-cli"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "chunk_000.json").write_text(json.dumps(payload), encoding="utf-8")
        assert "--word_timestamps" in command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ta.subprocess, "run", fake_run)
    values = ta.WhisperCliAdapter()._transcribe_one(request, chunk)
    assert values[0]["text"].strip() == "spoken words"
    assert [w["word"].strip() for w in values[0]["words"]] == ["spoken", "words"]


def test_whisper_cli_without_words_in_json_is_fail_open(tmp_path, monkeypatch):
    chunk = _Chunk()
    chunk.path = tmp_path / "chunk_000.wav"
    chunk.path.write_bytes(b"")
    request = _Request()
    request.work_dir = tmp_path

    def fake_run(command, **kwargs):
        out_dir = tmp_path / "whisper-cli"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "chunk_000.json").write_text(
            json.dumps({"segments": [{"start": 0.0, "end": 1.0, "text": "plain"}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ta.subprocess, "run", fake_run)
    values = ta.WhisperCliAdapter()._transcribe_one(request, chunk)
    assert values[0]["text"] == "plain"
    assert not values[0].get("words")


# --- receipts: schema bump + words round-trip -----------------------------------

def test_receipt_schema_was_bumped_for_words():
    assert chunks.RECEIPT_SCHEMA >= 2


def test_old_schema_receipt_file_is_ignored(tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = AudioChunk(0, audio, 0.0, 5.0, chunks._sha256(audio))
    path = tmp_path / "receipts.json"

    # A pre-bump store: schema_version 1, segment-only payloads. Any key layout
    # from the old scheme must be unreachable after the bump.
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "any-old-key": {
                        "chunk_sha256": chunk.sha256,
                        "segments": [{"start": 0.0, "end": 1.0, "text": "stale"}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    store = ChunkReceiptStore(path)
    assert store.get("local-http", "model", "auto", chunk) is None
    assert store._data["entries"] == {}


def test_receipts_round_trip_words(tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = AudioChunk(0, audio, 7.0, 5.0, chunks._sha256(audio))
    path = tmp_path / "receipts.json"
    values = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "cached",
            "words": [{"word": "cached", "start": 0.1, "end": 0.9}],
        }
    ]
    store = ChunkReceiptStore(path)
    store.put("local-http", "model", "auto", chunk, values)
    store.flush()
    cached = ChunkReceiptStore(path).get("local-http", "model", "auto", chunk)
    segments = ta._local_segments(
        cached, chunk=chunk, adapter="local-http", model="model", language="auto"
    )
    # word timestamps shifted by the chunk offset, same as the segment itself
    assert segments[0].start == 7.0
    assert segments[0].words[0].start == pytest.approx(7.1)
    assert segments[0].words[0].end == pytest.approx(7.9)
