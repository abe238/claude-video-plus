#!/usr/bin/env python3
"""Transcribe a video via Groq or OpenAI Whisper API.

Strategy: extract audio (mono 16kHz mp3, tiny payload), upload to whichever
API has a key. Returns segments in the same shape as transcribe.parse_vtt so
the rest of the pipeline (filter_range, format_transcript) doesn't care where
the transcript came from.

Pure stdlib — no `pip install groq` or `pip install openai` needed.
"""
from __future__ import annotations

import io
import json
import math
import mimetypes
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"

OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MODEL = "whisper-1"

# Both Groq's free tier and OpenAI whisper-1 cap uploads at 25 MB. We target a
# margin under that so multipart framing overhead never pushes a chunk over.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024


def plan_chunks(
    total_seconds: float,
    total_bytes: int,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> list[tuple[float, float]]:
    """Split a duration into contiguous (offset, duration) chunks under max_bytes.

    Size scales linearly with duration (constant-bitrate mono mp3), so an even
    time split yields evenly-sized chunks. Returns a single full-length chunk
    when the audio already fits.
    """
    if total_bytes <= max_bytes or total_seconds <= 0:
        return [(0.0, total_seconds)]

    n = math.ceil(total_bytes / max_bytes)
    chunk = total_seconds / n
    plan: list[tuple[float, float]] = []
    for i in range(n):
        offset = i * chunk
        # The last chunk absorbs any rounding remainder so durations sum exactly.
        duration = (total_seconds - offset) if i == n - 1 else chunk
        plan.append((round(offset, 3), round(duration, 3)))
    return plan


def load_api_key(preferred: str | None = None) -> tuple[str, str] | tuple[None, None]:
    """Return (backend, api_key). Prefers Groq, falls back to OpenAI.

    If `preferred` is "groq" or "openai", only that backend's key is considered.
    """
    def _from_env(name: str) -> str | None:
        value = os.environ.get(name)
        return value.strip() if value else None

    def _from_dotenv(path: Path, name: str) -> str | None:
        if not path.exists():
            return None
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() != name:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                return value or None
        except OSError:
            return None
        return None

    dotenv_paths = [
        Path.home() / ".config" / "watch" / ".env",
        Path.cwd() / ".env",
    ]

    candidates = (("GROQ_API_KEY", "groq"), ("OPENAI_API_KEY", "openai"))
    if preferred is not None:
        candidates = tuple(c for c in candidates if c[1] == preferred)

    for key_name, backend in candidates:
        value = _from_env(key_name)
        if not value:
            for candidate in dotenv_paths:
                value = _from_dotenv(candidate, key_name)
                if value:
                    break
        if value:
            return backend, value

    return None, None


def extract_audio(
    video_path: str,
    out_path: Path,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> Path:
    """Extract mono audio, limiting work to an optional requested source range."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = float(start_seconds or 0.0)
    if start < 0:
        raise SystemExit("transcription range start must be non-negative")
    if end_seconds is not None and float(end_seconds) <= start:
        raise SystemExit("transcription range end must be greater than range start")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
    ]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(Path(video_path).resolve())]
    if end_seconds is not None:
        cmd += ["-t", f"{float(end_seconds) - start:.3f}"]
    cmd += [
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "64k",
        str(out_path.resolve()),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg audio extraction failed: {result.stderr.strip()}")
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise SystemExit("ffmpeg produced no audio — video may have no audio track")
    return out_path


def audio_duration(audio_path: Path) -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    if shutil.which("ffprobe") is None:
        raise SystemExit("ffprobe is not installed. Install with: brew install ffmpeg")

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path.resolve()),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffprobe failed: {result.stderr.strip()}")
    fmt = json.loads(result.stdout or "{}").get("format", {})
    return float(fmt.get("duration") or 0.0)


def split_audio(
    full_audio: Path,
    work_dir: Path,
    plan: list[tuple[float, float]],
) -> list[tuple[Path, float]]:
    """Slice full_audio into per-plan chunk files, returning (path, offset) pairs.

    Uses stream copy (`-c copy`) so there is no re-encode and no quality loss;
    mp3 frame boundaries are close enough for transcription's purposes.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    work_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple[Path, float]] = []
    for index, (offset, duration) in enumerate(plan):
        out_path = work_dir / f"chunk_{index:03d}.mp3"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", f"{offset:.3f}",
            "-i", str(full_audio.resolve()),
            "-t", f"{duration:.3f}",
            "-c", "copy",
            str(out_path.resolve()),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise SystemExit(
                f"ffmpeg failed to split audio chunk {index + 1}: {result.stderr.strip()}"
            )
        chunks.append((out_path, offset))
    return chunks


def build_multipart(fields: dict[str, object], file_path: Path) -> tuple[bytes, str]:
    """Assemble a multipart/form-data body the Whisper APIs accept.

    Whisper's multipart upload is small and predictable — doing it by hand
    keeps us on pure stdlib instead of pulling requests/groq/openai SDKs.
    A list/tuple value emits one part per item (repeated-field form syntax,
    e.g. ``timestamp_granularities[]``).
    """
    boundary = f"----WatchBoundary{uuid.uuid4().hex}"
    eol = b"\r\n"
    buf = io.BytesIO()

    for name, value in fields.items():
        items = value if isinstance(value, (list, tuple)) else (value,)
        for item in items:
            buf.write(f"--{boundary}".encode()); buf.write(eol)
            buf.write(f'Content-Disposition: form-data; name="{name}"'.encode()); buf.write(eol)
            buf.write(eol)
            buf.write(str(item).encode()); buf.write(eol)

    mimetype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    buf.write(f"--{boundary}".encode()); buf.write(eol)
    buf.write(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode()
    )
    buf.write(eol)
    buf.write(f"Content-Type: {mimetype}".encode()); buf.write(eol)
    buf.write(eol)
    buf.write(file_path.read_bytes())
    buf.write(eol)
    buf.write(f"--{boundary}--".encode()); buf.write(eol)

    return buf.getvalue(), boundary


# Backward-compatible private name used by the pre-P11 tests.
_build_multipart = build_multipart


MAX_ATTEMPTS = 4       # initial + 3 retries
MAX_429_RETRIES = 2
RETRY_BASE_DELAY = 2.0


def _post_whisper(
    endpoint: str,
    api_key: str,
    model: str,
    audio_path: Path,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    language: str = "auto",
) -> dict:
    if not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_ATTEMPTS}")
    fields: dict[str, object] = {
        "model": model,
        "response_format": "verbose_json",
        "temperature": "0",
        # R2b: word-level timestamps. Both Groq and OpenAI accept this with
        # verbose_json; "segment" is requested too so segments keep coming back.
        # Responses without words parse fine (fail-open to segment-only).
        "timestamp_granularities[]": ["word", "segment"],
    }
    if language and language != "auto":
        fields["language"] = language
    body, boundary = build_multipart(fields, audio_path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        # Groq sits behind Cloudflare — the default `Python-urllib/3.x` UA
        # trips WAF rule 1010 (403) before auth even runs. Any non-default
        # UA clears it; we identify honestly.
        "User-Agent": "watch-skill/1.0 (+claude-code; python-urllib)",
    }

    context = ssl.create_default_context()
    rate_limit_hits = 0
    last_exc: Exception | None = None
    last_detail = ""

    for attempt in range(max_attempts):
        request = Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=300, context=context) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = _read_error_body(exc)
            last_exc, last_detail = exc, detail

            # 4xx other than 429 are client errors — no retry will fix them.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise SystemExit(f"Whisper request failed: {exc}{detail}")

            if exc.code == 429:
                rate_limit_hits += 1
                if rate_limit_hits >= MAX_429_RETRIES:
                    raise SystemExit(f"Whisper request failed: {exc}{detail}")
                delay = _retry_after(exc) or RETRY_BASE_DELAY * (2 ** attempt) + 1
            else:
                delay = RETRY_BASE_DELAY * (2 ** attempt)

            if attempt < max_attempts - 1:
                print(
                    f"[watch] whisper HTTP {exc.code} — retrying in {delay:.1f}s "
                    f"(attempt {attempt + 2}/{max_attempts})",
                    file=sys.stderr,
                )
                time.sleep(delay)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
            last_exc, last_detail = exc, ""
            if attempt < max_attempts - 1:
                delay = RETRY_BASE_DELAY * (attempt + 1)
                print(
                    f"[watch] whisper network error ({type(exc).__name__}: {exc}) — "
                    f"retrying in {delay:.1f}s (attempt {attempt + 2}/{max_attempts})",
                    file=sys.stderr,
                )
                time.sleep(delay)
            continue

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Whisper returned non-JSON response: {exc}: {payload[:200]}")

    raise SystemExit(
        f"Whisper request failed after {max_attempts} attempts: {type(last_exc).__name__}"
    )


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if not body:
        return ""
    try:
        return f" — {body.decode('utf-8', errors='replace')[:400]}"
    except Exception:
        return ""


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    header = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def shift_segments(segments: list[dict], offset_seconds: float) -> list[dict]:
    """Return a copy of segments with start/end shifted by offset_seconds.

    Each chunk is transcribed in isolation, so Whisper returns 0-based timestamps
    per chunk; shifting by the chunk's offset stitches them into source time.
    """
    if offset_seconds == 0:
        return segments
    shifted: list[dict] = []
    for segment in segments:
        value = dict(segment)
        value["start"] = round(float(segment["start"]) + offset_seconds, 2)
        value["end"] = round(float(segment["end"]) + offset_seconds, 2)
        if isinstance(value.get("words"), list):
            # R2b: nested word timestamps shift with their segment, or they'd
            # silently keep chunk-local time while the segment moved.
            value["words"] = [
                {
                    **word,
                    "start": round(float(word["start"]) + offset_seconds, 2),
                    "end": round(float(word["end"]) + offset_seconds, 2),
                }
                for word in value["words"]
            ]
        shifted.append(value)
    return shifted


def _clean_words(raw: object) -> list[dict]:
    """Normalize a backend word list to {word, start, end}; drop malformed entries."""
    words: list[dict] = []
    if not isinstance(raw, list):
        return words
    for entry in raw:
        if not isinstance(entry, dict) or not str(entry.get("word") or "").strip():
            continue
        try:
            words.append({
                "word": str(entry["word"]),
                "start": round(float(entry["start"]), 3),
                "end": round(float(entry["end"]), 3),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return words


def segments_from_response(data: dict) -> list[dict]:
    """Convert Whisper verbose_json into our {start, end, text[, words]} format.

    Word timestamps (R2b) are fail-open: nested per-segment words are used when
    a backend provides them; otherwise top-level ``words`` (OpenAI/Groq
    ``timestamp_granularities[]`` style) are assigned to segments by start time;
    absent words simply yield segment-only output.
    """
    top_words = _clean_words(data.get("words"))
    out: list[dict] = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        value = {
            "start": round(float(seg.get("start") or 0.0), 2),
            "end": round(float(seg.get("end") or 0.0), 2),
            "text": text,
        }
        words = _clean_words(seg.get("words"))
        if not words and top_words:
            words = [w for w in top_words if value["start"] <= w["start"] < value["end"]]
        if words:
            value["words"] = words
        out.append(value)

    if not out:
        full = (data.get("text") or "").strip()
        if full:
            out.append({"start": 0.0, "end": 0.0, "text": full})

    return out


_segments_from_response = segments_from_response


def transcribe_chunks(
    chunks: list[tuple[Path, float]],
    transcribe_one,
) -> list[dict]:
    """Transcribe each chunk, shift its segments by the chunk offset, concatenate.

    A chunk that fails after its own retries is logged and skipped so one bad
    slice doesn't discard the whole transcript. Raises only if every chunk fails.
    """
    segments: list[dict] = []
    failures = 0
    for index, (path, offset) in enumerate(chunks):
        try:
            chunk_segments = transcribe_one(path)
        except SystemExit as exc:
            failures += 1
            print(
                f"[watch] chunk {index + 1}/{len(chunks)} failed — skipping ({exc})",
                file=sys.stderr,
            )
            continue
        segments.extend(shift_segments(chunk_segments, offset))
        print(
            f"[watch] chunk {index + 1}/{len(chunks)} → {len(chunk_segments)} segments",
            file=sys.stderr,
        )

    if failures == len(chunks):
        raise SystemExit("Whisper failed on every audio chunk")
    return segments


def transcribe_file(
    backend: str,
    api_key: str,
    audio_path: Path,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    language: str = "auto",
) -> list[dict]:
    """Upload one audio file and return its 0-based segments."""
    if backend == "groq":
        response = _post_whisper(
            GROQ_ENDPOINT, api_key, GROQ_MODEL, audio_path,
            max_attempts=max_attempts, language=language,
        )
    elif backend == "openai":
        response = _post_whisper(
            OPENAI_ENDPOINT, api_key, OPENAI_MODEL, audio_path,
            max_attempts=max_attempts, language=language,
        )
    else:
        raise SystemExit(f"Unknown whisper backend: {backend}")
    return segments_from_response(response)


_transcribe_file = transcribe_file


def transcribe_video(
    video_path: str,
    audio_out: Path,
    backend: str | None = None,
    api_key: str | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    language: str = "auto",
) -> tuple[list[dict], str]:
    """Run the full flow: extract audio → upload → parse segments.

    Returns (segments, backend_used). Raises SystemExit on any failure.
    """
    if backend is None or api_key is None:
        detected_backend, detected_key = load_api_key()
        backend = backend or detected_backend
        api_key = api_key or detected_key

    if not backend or not api_key:
        setup_py = Path(__file__).resolve().parent / "setup.py"
        raise SystemExit(
            "No Whisper API key available. Set GROQ_API_KEY (preferred) or OPENAI_API_KEY "
            "in the environment or in ~/.config/watch/.env. "
            f"Run `python3 {setup_py}` to configure."
        )

    print(f"[watch] extracting audio for Whisper ({backend})…", file=sys.stderr)
    audio_path = extract_audio(
        video_path,
        audio_out,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    audio_bytes = audio_path.stat().st_size

    def transcribe_one(path: Path) -> list[dict]:
        return transcribe_file(backend, api_key, path, language=language)

    if audio_bytes <= MAX_UPLOAD_BYTES:
        print(
            f"[watch] audio: {audio_bytes / 1024:.0f} kB — uploading to {backend} Whisper…",
            file=sys.stderr,
        )
        segments = transcribe_one(audio_path)
    else:
        duration = audio_duration(audio_path)
        plan = plan_chunks(duration, audio_bytes, MAX_UPLOAD_BYTES)
        print(
            f"[watch] audio: {audio_bytes / (1024 * 1024):.0f} MB exceeds "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB — splitting into {len(plan)} chunks…",
            file=sys.stderr,
        )
        chunks = split_audio(audio_path, audio_out.parent / "chunks", plan)
        segments = transcribe_chunks(chunks, transcribe_one)

    if start_seconds:
        segments = shift_segments(segments, float(start_seconds))

    if not segments:
        raise SystemExit("Whisper returned no transcript segments")

    print(f"[watch] transcribed {len(segments)} segments via {backend}", file=sys.stderr)
    return segments, backend


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: whisper.py <video-path> [<audio-out.mp3>] [--backend groq|openai]", file=sys.stderr)
        raise SystemExit(2)

    video = sys.argv[1]
    audio_out = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path("audio.mp3")
    backend_override = None
    if "--backend" in sys.argv:
        backend_override = sys.argv[sys.argv.index("--backend") + 1]

    segments, backend = transcribe_video(video, audio_out, backend=backend_override)
    print(json.dumps({"backend": backend, "segments": segments}, indent=2))
