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


# 2: R2b word-level timestamps — cached segment payloads may now carry a
# "words" list. Old segment-only receipts would silently mask the feature on
# resume, so the bump invalidates them wholesale (file-level via _read, and
# key-level because _key hashes the schema number).
RECEIPT_SCHEMA = 2
MAX_RECEIPT_ENTRIES = 512
RECEIPT_FLUSH_EVERY = 5

# Audio is prepared at 64 kbps mono, so ~480 KB per minute. 1.5 MB is roughly a
# 3-minute chunk.
#
# This was 24 MB, which is not a transcription bound at all -- it is the cloud
# Whisper *upload* limit, inherited from when cloud was the only backend. Local
# adapters are tried first now, so that limit handed a CPU-bound model a ~50
# minute chunk in a single request, which cannot finish inside WATCH_STT_TIMEOUT.
# The cloud path is unaffected in correctness: it simply makes more, smaller
# requests, and a failed chunk now costs 3 minutes of rework instead of 50.
DEFAULT_MAX_CHUNK_BYTES = 1536 * 1024
SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class AudioChunk:
    index: int
    path: Path
    source_offset: float
    duration: float
    sha256: str
    # R2a-1: silence-classified at the shared chunk layer, BEFORE any adapter.
    # Never cached in receipts — recomputed each run, so a threshold change can
    # never serve a stale classification.
    silent: bool = False


@dataclass(frozen=True)
class PreparedAudio:
    audio_path: Path
    chunks: tuple[AudioChunk, ...]
    source_start: float
    source_end: float
    # R2c: planning caveats (e.g. hard_cut boundaries with no silence nearby),
    # propagated into TranscriptResult.warnings by _run_chunked.
    warnings: tuple[str, ...] = ()

    @property
    def all_silent(self) -> bool:
        """Whole-input no_speech ONLY when every chunk is silent (binding
        aggregation rule: a silent chunk must never suppress speech elsewhere)."""
        return bool(self.chunks) and all(c.silent for c in self.chunks)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# Audio prep must not be able to hang the pipeline forever. A stalled network
# mount or a malformed container previously blocked with no output and no
# timeout; ffmpeg is not guaranteed to exit on its own.
FFMPEG_TIMEOUT_SECONDS = 300
FFPROBE_TIMEOUT_SECONDS = 30


def _run_ffmpeg(command: list[str], *, failure: str) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{failure}: ffmpeg timed out after {FFMPEG_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"{failure}: ffmpeg exited {result.returncode}")


def audio_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is unavailable")
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
                str(path.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s"
        ) from exc
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
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path.resolve()),
                "-af", "silencedetect=noise=-35dB:d=0.40", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ()  # silence detection is an optimization; degrade to even chunking
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


# R2a-1 classifier thresholds. Not stored in receipts because no_speech is
# never cached (see AudioChunk.silent) — a change here takes effect on the very
# next run with no invalidation machinery needed.
SILENCE_CLASSIFIER_VERSION = 1
# Flat threshold ONLY. 1.2.0 also used max(0.5s, 2% of chunk duration), which
# on a ~180s chunk discarded up to 3.6s of genuine speech — a chunk holding one
# short sentence was classified silent (L6 review finding). Any utterance
# longer than this constant keeps its chunk.
MIN_SPEECH_SECONDS = 0.5


# R2c loose fallback thresholds: used for chunk PLANNING only (never for the
# no_speech classifier) when the tight pass finds no silence near a needed cut.
LOOSE_SILENCE_NOISE = "-30dB"
LOOSE_SILENCE_DURATION = 0.2


def silence_intervals(
    audio_path: Path,
    *,
    noise: str = "-35dB",
    min_duration: float = 0.40,
) -> tuple[tuple[float, float], ...] | None:
    """(start, end) silence spans from ffmpeg silencedetect, audio-local time.
    ``None`` means the classifier itself failed — callers must treat that as
    speech everywhere (a broken instrument never gates)."""
    if shutil.which("ffmpeg") is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path.resolve()),
                "-af", f"silencedetect=noise={noise}:d={min_duration}", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for kind, raw in SILENCE_RE.findall(result.stderr or ""):
        value = max(0.0, float(raw))
        if kind == "start":
            start = value
        elif start is not None:
            spans.append((start, value))
            start = None
    if start is not None:  # silence ran to EOF
        spans.append((start, float("inf")))
    return tuple(spans)


def _interval_midpoints(
    intervals: tuple[tuple[float, float], ...] | None,
) -> tuple[float, ...]:
    """Silence-span midpoints usable as chunk-planning boundaries."""
    if not intervals:
        return ()
    finite = [(s, e) for s, e in intervals if e != float("inf")]
    return tuple(sorted(round((s + e) / 2.0, 3) for s, e in finite if (s + e) / 2.0 > 0))


def classify_chunk_silence(
    chunks: tuple[AudioChunk, ...],
    intervals: tuple[tuple[float, float], ...] | None,
    *,
    source_start: float,
    total_duration: float,
) -> tuple[AudioChunk, ...]:
    """Mark chunks silent when silence covers them almost entirely.

    A chunk is silent iff its non-silent time is under
    max(MIN_SPEECH_SECONDS, MIN_SPEECH_FRACTION * chunk duration) — quiet
    speech above the silencedetect threshold therefore always counts as speech
    (false-negative guard). ``intervals=None`` (classifier failure) marks
    nothing silent."""
    if intervals is None:
        return chunks
    from dataclasses import replace
    out = []
    for chunk in chunks:
        local_start = chunk.source_offset - source_start
        local_end = min(local_start + chunk.duration, total_duration)
        silent_time = 0.0
        for s, e in intervals:
            e = min(e, local_end)
            s = max(s, local_start)
            if e > s:
                silent_time += e - s
        speech_time = max(0.0, (local_end - local_start) - silent_time)
        out.append(replace(chunk, silent=speech_time < MIN_SPEECH_SECONDS))
    return tuple(out)


def plan_silence_aware_chunks(
    duration: float,
    total_bytes: int,
    *,
    max_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    silence_boundaries: Iterable[float] = (),
) -> tuple[tuple[float, float], ...]:
    """Plan contiguous chunks, moving even cuts to nearby silence when safe."""
    return _plan_with_hard_cuts(
        duration, total_bytes, max_bytes=max_bytes, silence_boundaries=silence_boundaries
    )[0]


def _plan_with_hard_cuts(
    duration: float,
    total_bytes: int,
    *,
    max_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    silence_boundaries: Iterable[float] = (),
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...]]:
    """Plan chunks and report the even-cut targets that had NO nearby silence.

    Returns (plan, hard_cut_targets). A hard cut lands mid-audio and may split
    a word; callers can retry with looser silence detection or surface a
    warning (R2c).
    """
    if duration <= 0:
        raise ValueError("audio duration must be positive")
    count = max(1, math.ceil(total_bytes / max_bytes))
    if count == 1:
        return ((0.0, round(duration, 3)),), ()

    silences = tuple(sorted(float(value) for value in silence_boundaries if 0 < value < duration))
    ideal = duration / count
    cuts = [0.0]
    hard: list[float] = []
    for index in range(1, count):
        target = ideal * index
        window = min(15.0, max(2.0, ideal * 0.20))
        candidates = [point for point in silences if abs(point - target) <= window]
        if candidates:
            cut = min(candidates, key=lambda point: abs(point - target))
        else:
            cut = target
            hard.append(round(target, 3))
        minimum = cuts[-1] + min(1.0, ideal * 0.10)
        maximum = duration - (count - index) * min(1.0, ideal * 0.10)
        cuts.append(min(max(cut, minimum), maximum))
    cuts.append(duration)
    plan = tuple(
        (round(cuts[index], 3), round(cuts[index + 1] - cuts[index], 3))
        for index in range(len(cuts) - 1)
    )
    return plan, tuple(hard)


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
    # One tight silencedetect scan is SHARED between the no_speech classifier
    # and chunk planning — never rescanned. The loose pass below is planning-
    # only and on-demand, so silencedetect runs at most twice per prepare.
    intervals = silence_intervals(audio_path)
    boundaries = _interval_midpoints(intervals)
    plan, hard = _plan_with_hard_cuts(
        duration,
        audio_path.stat().st_size,
        max_bytes=max_chunk_bytes,
        silence_boundaries=boundaries,
    )
    warnings: tuple[str, ...] = ()
    if hard:
        # R2c: the tight pass (-35dB/0.40s) left cuts with no usable silence.
        # Retry planning with a looser scan; classification keeps the tight
        # intervals (quiet speech must never become no_speech).
        loose = silence_intervals(
            audio_path, noise=LOOSE_SILENCE_NOISE, min_duration=LOOSE_SILENCE_DURATION
        )
        loose_boundaries = _interval_midpoints(loose)
        if loose_boundaries:
            plan, hard = _plan_with_hard_cuts(
                duration,
                audio_path.stat().st_size,
                max_bytes=max_chunk_bytes,
                silence_boundaries=tuple(sorted(set(boundaries) | set(loose_boundaries))),
            )
        warnings = tuple(
            f"hard_cut: no silence near {target:.1f}s even at loose threshold; "
            "chunk boundary may split audio mid-word"
            for target in hard
        )
    chunks = _materialize_chunks(
        audio_path, work_dir / "chunks", plan, source_start=source_start
    )
    chunks = classify_chunk_silence(
        chunks, intervals, source_start=source_start, total_duration=duration
    )
    return PreparedAudio(
        audio_path=audio_path,
        chunks=chunks,
        source_start=round(source_start, 3),
        source_end=round(source_end, 3),
        warnings=warnings,
    )


class ChunkReceiptStore:
    """Owner-only active-task receipt store for completed chunk outputs."""

    def __init__(self, path: Path, *, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._data = self._read()
        self._pending = 0

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
            # dict preserves insertion order, so this is true FIFO -- but only
            # because _write() no longer sorts the keys on the way out. Sorting
            # made a reloaded store evict in hash order instead of oldest-first.
            for key in tuple(entries)[: len(entries) - MAX_RECEIPT_ENTRIES]:
                del entries[key]

        # Batch the flush. Every put used to rewrite the whole JSON file and
        # fsync it, so a 100-chunk video did 100 full-file rewrites of a file
        # that only grows -- quadratic I/O for a resume cache. Crash exposure is
        # now at most RECEIPT_FLUSH_EVERY - 1 chunks of rework.
        self._pending += 1
        if self._pending >= RECEIPT_FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        """Persist any buffered receipts. Safe to call when nothing is pending."""
        if not self.enabled or not self._pending:
            return
        self._write()
        self._pending = 0

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{id(self)}.tmp")
        # No sort_keys: insertion order IS the eviction order (FIFO). Sorting
        # here made a reloaded store evict by key hash rather than oldest-first.
        payload = json.dumps(self._data, separators=(",", ":")) + "\n"
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
