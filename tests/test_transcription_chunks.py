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


# --- R2c: tight -> loose silencedetect fallback + hard_cut warnings -------------
#
# Invariants: (1) when the tight pass yields usable boundaries, planning inputs
# are unchanged, so chunk boundaries are byte-identical to before; the loose
# pass never runs. (2) audio with no silence at all still chunks, each forced
# cut classified hard_cut with a warning surfaced through PreparedAudio.
# (3) silencedetect never runs three times: the tight scan is shared between
# classification and planning, and the loose scan is on-demand only.

import subprocess as _subprocess


def _make_audio(path, *parts):
    inputs, filters = [], []
    for i, part in enumerate(parts):
        inputs += ["-f", "lavfi", "-t", "4", "-i", part]
        filters.append(f"[{i}:a]")
    filter_complex = "".join(filters) + f"concat=n={len(parts)}:v=0:a=1[out]"
    _subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", filter_complex, "-map", "[out]",
         "-ac", "1", "-ar", "16000", "-y", str(path)],
        check=True, capture_output=True,
    )
    return path


def _counting_run(monkeypatch):
    """Count silencedetect invocations while letting everything run for real."""
    counter = {"silencedetect": 0}
    real_run = _subprocess.run

    def counting(cmd, **kwargs):
        if any("silencedetect" in str(part) for part in cmd):
            counter["silencedetect"] += 1
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(chunks.subprocess, "run", counting)
    return counter


def _assert_tiling(prepared):
    """Chunk offsets + durations must tile [source_start, source_end] exactly."""
    cursor = prepared.source_start
    for chunk in prepared.chunks:
        assert chunk.source_offset == pytest.approx(cursor, abs=0.002)
        cursor += chunk.duration
    assert cursor == pytest.approx(prepared.source_end, abs=0.02)


def test_normal_audio_keeps_boundaries_and_never_runs_loose_pass(tmp_path, monkeypatch):
    audio = _make_audio(
        tmp_path / "normal.wav",
        "sine=frequency=440", "anullsrc=r=16000:cl=mono", "sine=frequency=440",
    )
    # Compute the pre-change expectation from the (unchanged) pure planner fed
    # with tight-pass boundaries, exactly as prepare_audio wires it.
    work = tmp_path / "probe"
    probe_path, start, end = chunks.extract_audio_range(audio, work / "audio-range.mp3")
    intervals = chunks.silence_intervals(probe_path)
    finite = [(s, e) for s, e in intervals if e != float("inf")]
    boundaries = tuple(sorted(round((s + e) / 2.0, 3) for s, e in finite if (s + e) / 2.0 > 0))
    max_bytes = probe_path.stat().st_size // 2 + 1  # force exactly 2 chunks
    expected = chunks.plan_silence_aware_chunks(
        end - start, probe_path.stat().st_size,
        max_bytes=max_bytes, silence_boundaries=boundaries,
    )

    counter = _counting_run(monkeypatch)
    prepared = chunks.prepare_audio(audio, tmp_path / "work", max_chunk_bytes=max_bytes)
    assert counter["silencedetect"] == 1  # one shared scan: no loose pass, no rescan
    assert prepared.warnings == ()
    got = tuple(
        (round(c.source_offset - prepared.source_start, 3), c.duration)
        for c in prepared.chunks
    )
    assert got == expected  # byte-identical boundaries when the tight pass works
    _assert_tiling(prepared)


def test_no_silence_audio_chunks_with_hard_cut_warning(tmp_path, monkeypatch):
    audio = _make_audio(
        tmp_path / "tone.wav", "sine=frequency=440", "sine=frequency=523",
    )
    counter = _counting_run(monkeypatch)
    size = chunks.extract_audio_range(
        audio, tmp_path / "size-probe" / "audio-range.mp3"
    )[0].stat().st_size
    counter["silencedetect"] = 0  # only count prepare_audio's own scans
    prepared = chunks.prepare_audio(
        audio, tmp_path / "work", max_chunk_bytes=size // 2 + 1
    )
    assert len(prepared.chunks) >= 2
    # Tight found nothing usable -> exactly one loose retry, never a third scan.
    assert counter["silencedetect"] == 2
    assert any("hard_cut" in warning for warning in prepared.warnings)
    _assert_tiling(prepared)


def test_prepared_audio_warnings_default_empty():
    prepared = PreparedAudio(Path("a.mp3"), (), 0.0, 1.0)
    assert prepared.warnings == ()


def test_hard_cut_warnings_propagate_through_run_chunked(tmp_path):
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = AudioChunk(0, audio, 0.0, 5.0, "sha")
    prepared = PreparedAudio(
        audio, (chunk,), 0.0, 5.0,
        warnings=("hard_cut: no silence near 2.5s; cutting mid-audio",),
    )
    request = TranscriptionRequest(
        media_path=tmp_path / "clip.mp4",
        work_dir=tmp_path,
        adapter_order=(),
        prepared_audio=prepared,
        config={"receipts": False},
    )
    result = adapters._run_chunked(
        request,
        ChunkReceiptStore(tmp_path / "receipts.json", enabled=False),
        adapter="local-http",
        model="model",
        transcribe_one=lambda _chunk: [{"start": 0.0, "end": 1.0, "text": "ok"}],
        remote=False,
    )
    assert any("hard_cut" in warning for warning in result.warnings)
