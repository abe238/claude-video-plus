#!/usr/bin/env python3
"""Range-only audio preparation, silence-aware chunks, and resumable receipts.

This Module owns transient transcription work under the caller-provided working
directory.  It does not create a durable evidence cache; P19 owns that broader
state lifecycle.  Receipts are owner-only and atomically replaced so an
interrupted task can skip chunks that already completed successfully.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


RECEIPT_SCHEMA = 1
MAX_RECEIPT_ENTRIES = 512
DEFAULT_MAX_CHUNK_BYTES = 24 * 1024 * 1024
SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class AudioChunk:
    index: int
    path: Path
    source_offset: float
    duration: float
    sha256: str


@dataclass(frozen=True)
class PreparedAudio:
    audio_path: Path
    chunks: tuple[AudioChunk, ...]
    source_start: float
    source_end: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_ffmpeg(command: list[str], *, failure: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{failure}: ffmpeg exited {result.returncode}")


def audio_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is unavailable")
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
            str(path.resolve()),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe could not determine audio duration")
    try:
        duration = float(json.loads(result.stdout or "{}").get("format", {}).get("duration") or 0)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe returned invalid duration metadata") from exc
    if duration <= 0:
        raise RuntimeError("extracted audio has no positive duration")
    return duration


def extract_audio_range(
    media_path: str | Path,
    output_path: Path,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> tuple[Path, float, float]:
    """Extract only the requested source interval and return absolute bounds."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is unavailable")
    start = float(start_seconds or 0.0)
    if start < 0:
        raise ValueError("range start must be non-negative")
    if end_seconds is not None and float(end_seconds) <= start:
        raise ValueError("range end must be greater than range start")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", str(Path(media_path).expanduser().resolve())]
    if end_seconds is not None:
        command += ["-t", f"{float(end_seconds) - start:.3f}"]
    command += [
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(output_path.resolve()),
    ]
    _run_ffmpeg(command, failure="audio range extraction failed")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("audio range extraction produced no audio")
    duration = audio_duration(output_path)
    return output_path, start, start + duration


def detect_silence_boundaries(audio_path: Path) -> tuple[float, ...]:
    """Return silence midpoints; failure safely degrades to even chunking."""
    if shutil.which("ffmpeg") is None:
        return ()
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path.resolve()),
            "-af", "silencedetect=noise=-35dB:d=0.40", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    starts: list[float] = []
    boundaries: list[float] = []
    for kind, raw in SILENCE_RE.findall(result.stderr or ""):
        value = max(0.0, float(raw))
        if kind == "start":
            starts.append(value)
        elif starts:
            boundaries.append((starts.pop(0) + value) / 2.0)
        else:
            boundaries.append(value)
    return tuple(sorted(set(round(value, 3) for value in boundaries if value > 0)))


def plan_silence_aware_chunks(
    duration: float,
    total_bytes: int,
    *,
    max_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    silence_boundaries: Iterable[float] = (),
) -> tuple[tuple[float, float], ...]:
    """Plan contiguous chunks, moving even cuts to nearby silence when safe."""
    if duration <= 0:
        raise ValueError("audio duration must be positive")
    count = max(1, math.ceil(total_bytes / max_bytes))
    if count == 1:
        return ((0.0, round(duration, 3)),)

    silences = tuple(sorted(float(value) for value in silence_boundaries if 0 < value < duration))
    ideal = duration / count
    cuts = [0.0]
    for index in range(1, count):
        target = ideal * index
        window = min(15.0, max(2.0, ideal * 0.20))
        candidates = [point for point in silences if abs(point - target) <= window]
        cut = min(candidates, key=lambda point: abs(point - target)) if candidates else target
        minimum = cuts[-1] + min(1.0, ideal * 0.10)
        maximum = duration - (count - index) * min(1.0, ideal * 0.10)
        cuts.append(min(max(cut, minimum), maximum))
    cuts.append(duration)
    return tuple(
        (round(cuts[index], 3), round(cuts[index + 1] - cuts[index], 3))
        for index in range(len(cuts) - 1)
    )


def _materialize_chunks(
    audio_path: Path,
    chunk_dir: Path,
    plan: tuple[tuple[float, float], ...],
    *,
    source_start: float,
) -> tuple[AudioChunk, ...]:
    if len(plan) == 1:
        return (
            AudioChunk(
                index=0,
                path=audio_path,
                source_offset=round(source_start, 3),
                duration=plan[0][1],
                sha256=_sha256(audio_path),
            ),
        )
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[AudioChunk] = []
    for index, (offset, duration) in enumerate(plan):
        chunk_path = chunk_dir / f"chunk_{index:03d}.mp3"
        _run_ffmpeg(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{offset:.3f}", "-i", str(audio_path.resolve()),
                "-t", f"{duration:.3f}", "-c", "copy", str(chunk_path.resolve()),
            ],
            failure=f"audio chunk {index + 1} extraction failed",
        )
        if not chunk_path.is_file() or chunk_path.stat().st_size == 0:
            raise RuntimeError(f"audio chunk {index + 1} is empty")
        chunks.append(
            AudioChunk(
                index=index,
                path=chunk_path,
                source_offset=round(source_start + offset, 3),
                duration=duration,
                sha256=_sha256(chunk_path),
            )
        )
    return tuple(chunks)


def prepare_audio(
    media_path: str | Path,
    work_dir: Path,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
) -> PreparedAudio:
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path, source_start, source_end = extract_audio_range(
        media_path,
        work_dir / "audio-range.mp3",
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    duration = source_end - source_start
    plan = plan_silence_aware_chunks(
        duration,
        audio_path.stat().st_size,
        max_bytes=max_chunk_bytes,
        silence_boundaries=detect_silence_boundaries(audio_path),
    )
    chunks = _materialize_chunks(
        audio_path, work_dir / "chunks", plan, source_start=source_start
    )
    return PreparedAudio(
        audio_path=audio_path,
        chunks=chunks,
        source_start=round(source_start, 3),
        source_end=round(source_end, 3),
    )


class ChunkReceiptStore:
    """Owner-only active-task receipt store for completed chunk outputs."""

    def __init__(self, path: Path, *, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._data = self._read()

    def _read(self) -> dict:
        empty = {"schema_version": RECEIPT_SCHEMA, "entries": {}}
        if not self.enabled or not self.path.exists():
            return empty
        try:
            if self.path.stat().st_mode & 0o077:
                return empty
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != RECEIPT_SCHEMA or not isinstance(data.get("entries"), dict):
                return empty
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return empty

    @staticmethod
    def _key(adapter: str, model: str | None, language: str, chunk: AudioChunk) -> str:
        payload = {
            "schema": RECEIPT_SCHEMA,
            "adapter": adapter,
            "model": model,
            "language": language,
            "chunk_sha256": chunk.sha256,
            "source_offset": chunk.source_offset,
            "duration": chunk.duration,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get(
        self,
        adapter: str,
        model: str | None,
        language: str,
        chunk: AudioChunk,
    ) -> list[dict] | None:
        if not self.enabled:
            return None
        entry = self._data["entries"].get(self._key(adapter, model, language, chunk))
        if not isinstance(entry, dict) or entry.get("chunk_sha256") != chunk.sha256:
            return None
        segments = entry.get("segments")
        if not isinstance(segments, list):
            return None
        return [dict(segment) for segment in segments if isinstance(segment, Mapping)]

    def put(
        self,
        adapter: str,
        model: str | None,
        language: str,
        chunk: AudioChunk,
        segments: Iterable[Mapping[str, object]],
    ) -> None:
        if not self.enabled:
            return
        entries = self._data["entries"]
        entries[self._key(adapter, model, language, chunk)] = {
            "chunk_sha256": chunk.sha256,
            "segments": [dict(segment) for segment in segments],
        }
        if len(entries) > MAX_RECEIPT_ENTRIES:
            for key in tuple(entries)[: len(entries) - MAX_RECEIPT_ENTRIES]:
                del entries[key]
        self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{id(self)}.tmp")
        payload = json.dumps(self._data, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
