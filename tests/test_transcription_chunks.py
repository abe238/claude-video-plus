"""Focused P17/P18 range, chunk-planning, and receipt tests."""
from __future__ import annotations

from pathlib import Path

import pytest

import transcription_adapters as adapters
import transcription_chunks as chunks
import whisper
from transcription import TranscriptionRequest
from transcription_chunks import AudioChunk, ChunkReceiptStore, PreparedAudio


def test_range_extraction_limits_ffmpeg_command_and_returns_absolute_bounds(monkeypatch, tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    output = tmp_path / "audio.mp3"
    commands = []
    monkeypatch.setattr(chunks.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, *, failure):
        commands.append(command)
        output.write_bytes(b"audio")

    monkeypatch.setattr(chunks, "_run_ffmpeg", fake_run)
    monkeypatch.setattr(chunks, "audio_duration", lambda path: 15.0)
    path, start, end = chunks.extract_audio_range(
        media, output, start_seconds=30.0, end_seconds=45.0
    )
    assert path == output
    assert (start, end) == (30.0, 45.0)
    command = commands[0]
    assert command[command.index("-ss") + 1] == "30.000"
    assert command[command.index("-t") + 1] == "15.000"
    assert command.index("-ss") < command.index("-i")


def test_silence_aware_plan_moves_cuts_and_remains_contiguous():
    plan = chunks.plan_silence_aware_chunks(
        90.0,
        300,
        max_bytes=100,
        silence_boundaries=(28.0, 61.0),
    )
    assert plan == ((0.0, 28.0), (28.0, 33.0), (61.0, 29.0))
    assert sum(duration for _, duration in plan) == 90.0


def test_completed_chunk_receipt_is_reused_without_reprocessing(tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = AudioChunk(0, audio, 12.0, 5.0, "sha")
    prepared = PreparedAudio(audio, (chunk,), 12.0, 17.0)
    request = TranscriptionRequest(
        media_path=tmp_path / "clip.mp4",
        work_dir=tmp_path,
        adapter_order=(),
        prepared_audio=prepared,
        config={"receipts": True},
    )
    receipt_path = tmp_path / "receipts.json"
    calls = 0

    def transcribe_one(_chunk):
        nonlocal calls
        calls += 1
        return [{"start": 0.0, "end": 1.0, "text": "once"}]

    first = adapters._run_chunked(
        request,
        ChunkReceiptStore(receipt_path),
        adapter="local-http",
        model="model",
        transcribe_one=transcribe_one,
        remote=False,
    )
    second = adapters._run_chunked(
        request,
        ChunkReceiptStore(receipt_path),
        adapter="local-http",
        model="model",
        transcribe_one=lambda _chunk: (_ for _ in ()).throw(AssertionError("must reuse")),
        remote=False,
    )
    assert calls == 1
    assert first.segments[0].start == second.segments[0].start == 12.0
    assert second.diagnostics["processed_chunks"] == 0
    assert second.diagnostics["reused_chunks"] == 1
    assert receipt_path.stat().st_mode & 0o077 == 0


def test_legacy_whisper_range_api_restores_absolute_timestamps(monkeypatch, tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    audio = tmp_path / "audio.mp3"
    seen = {}

    def fake_extract(video_path, out_path, **kwargs):
        seen.update(kwargs)
        out_path.write_bytes(b"audio")
        return out_path

    monkeypatch.setattr(whisper, "extract_audio", fake_extract)
    monkeypatch.setattr(
        whisper,
        "transcribe_file",
        lambda *args, **kwargs: [{"start": 1.0, "end": 2.0, "text": "range"}],
    )
    segments, backend = whisper.transcribe_video(
        str(media),
        audio,
        backend="groq",
        api_key="secret",
        start_seconds=30.0,
        end_seconds=40.0,
    )
    assert backend == "groq"
    assert seen == {"start_seconds": 30.0, "end_seconds": 40.0}
    assert segments == [{"start": 31.0, "end": 32.0, "text": "range"}]


def test_invalid_range_is_rejected_before_subprocess(monkeypatch, tmp_path):
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(chunks.subprocess, "run", fake_run)
    monkeypatch.setattr(chunks.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    with pytest.raises(ValueError):
        chunks.extract_audio_range(
            tmp_path / "clip.mp4", tmp_path / "audio.mp3", start_seconds=10, end_seconds=9
        )
    assert called is False
