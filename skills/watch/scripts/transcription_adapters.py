#!/usr/bin/env python3
"""Concrete local, sidecar, YAP, and cloud transcript Adapters."""
from __future__ import annotations

import ipaddress
import json
import platform
import shutil
import subprocess
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

import whisper
from transcribe import filter_range, parse_subtitle
from transcription import (
    AdapterAvailability,
    TranscriptAttempt,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionRequest,
)
from transcription_chunks import AudioChunk, ChunkReceiptStore


def _discover_sidecar(media_path: Path) -> Path | None:
    """Return an exact same-basename VTT/SRT, preferring VTT."""
    parent = media_path.parent
    stem = media_path.stem.casefold()
    candidates: dict[str, Path] = {}
    try:
        for candidate in parent.iterdir():
            if (
                candidate.is_file()
                and candidate.stem.casefold() == stem
                and candidate.suffix.casefold() in {".vtt", ".srt"}
            ):
                candidates[candidate.suffix.casefold()] = candidate
    except OSError:
        return None
    return candidates.get(".vtt") or candidates.get(".srt")


def _local_segments(
    values: list[dict],
    *,
    chunk: AudioChunk,
    adapter: str,
    model: str | None,
    language: str,
) -> tuple[TranscriptSegment, ...]:
    output: list[TranscriptSegment] = []
    for value in values:
        if not str(value.get("text") or "").strip():
            continue
        output.append(
            TranscriptSegment.from_mapping(
                value,
                language=language,
                adapter=adapter,
                model=model,
                offset=chunk.source_offset,
            )
        )
    return tuple(output)


def _run_chunked(
    request: TranscriptionRequest,
    receipts: ChunkReceiptStore,
    *,
    adapter: str,
    model: str | None,
    transcribe_one,
    remote: bool,
) -> TranscriptResult:
    if request.prepared_audio is None:
        return TranscriptResult(
            state="fatal",
            adapter=adapter,
            model=model,
            language=request.language,
            failure_code="audio_not_prepared",
        )

    segments: list[TranscriptSegment] = []
    failed = 0
    processed = 0
    reused = 0
    warnings: list[str] = []
    started = time.monotonic()

    for chunk in request.prepared_audio.chunks:
        cached = receipts.get(adapter, model, request.language, chunk)
        if cached is not None:
            try:
                restored = _local_segments(
                    cached,
                    chunk=chunk,
                    adapter=adapter,
                    model=model,
                    language=request.language,
                )
                segments.extend(restored)
                reused += 1
                continue
            except (TypeError, ValueError):
                cached = None

        chunk_values: list[dict] | None = None
        for _attempt in range(request.max_attempts):
            try:
                chunk_values = transcribe_one(chunk)
                if chunk_values:
                    break
            except (Exception, SystemExit):
                chunk_values = None
        if not chunk_values:
            failed += 1
            warnings.append(f"chunk {chunk.index + 1} unavailable after bounded retries")
            continue
        processed += 1
        receipts.put(adapter, model, request.language, chunk, chunk_values)
        segments.extend(
            _local_segments(
                chunk_values,
                chunk=chunk,
                adapter=adapter,
                model=model,
                language=request.language,
            )
        )

    if not segments:
        state = "unavailable"
        failure_code = "adapter_exhausted"
    elif failed:
        state = "partial"
        failure_code = "incomplete_chunks"
    else:
        state = "success"
        failure_code = None
    attempt = TranscriptAttempt(
        adapter=adapter,
        state=state,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        model=model,
        failure_code=failure_code,
        processed_chunks=processed,
        reused_chunks=reused,
    )
    return TranscriptResult(
        state=state,
        segments=tuple(sorted(segments, key=lambda segment: (segment.start, segment.end))),
        adapter=adapter,
        model=model,
        language=request.language,
        warnings=tuple(warnings),
        attempts=(attempt,),
        failure_code=failure_code,
        diagnostics={
            "remote_transmission": remote and processed > 0,
            "processed_chunks": processed,
            "reused_chunks": reused,
            "failed_chunks": failed,
            "source_range": [
                request.prepared_audio.source_start,
                request.prepared_audio.source_end,
            ],
        },
    )


class SidecarAdapter:
    name = "sidecar"
    requires_audio = False
    is_remote = False

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        sidecar = _discover_sidecar(request.media_path)
        if sidecar is None:
            return AdapterAvailability(False, "sidecar_not_found")
        return AdapterAvailability(True)

    def transcribe(
        self,
        request: TranscriptionRequest,
        receipts: ChunkReceiptStore,
    ) -> TranscriptResult:
        del receipts
        sidecar = _discover_sidecar(request.media_path)
        if sidecar is None:
            return TranscriptResult(
                state="unavailable", adapter=self.name, language=request.language,
                failure_code="sidecar_not_found",
            )
        started = time.monotonic()
        try:
            raw = parse_subtitle(sidecar, strict=True)
            raw = filter_range(raw, request.start_seconds, request.end_seconds)
            segments = tuple(
                TranscriptSegment.from_mapping(
                    value,
                    language=request.language,
                    adapter=self.name,
                    model=sidecar.suffix.casefold().lstrip("."),
                )
                for value in raw
            )
        except (OSError, UnicodeError, ValueError):
            return TranscriptResult(
                state="unavailable",
                adapter=self.name,
                language=request.language,
                failure_code="invalid_sidecar",
                warnings=("same-basename sidecar is not valid timestamped UTF-8",),
            )
        if not segments:
            return TranscriptResult(
                state="unavailable",
                adapter=self.name,
                language=request.language,
                failure_code="sidecar_range_empty",
            )
        return TranscriptResult(
            state="success",
            segments=segments,
            adapter=self.name,
            model=sidecar.suffix.casefold().lstrip("."),
            language=request.language,
            attempts=(
                TranscriptAttempt(
                    adapter=self.name,
                    state="success",
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                ),
            ),
            diagnostics={"remote_transmission": False, "same_basename": True},
        )


def _loopback_endpoint(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("WATCH_STT_URL must be an http(s) loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("WATCH_STT_URL must not contain credentials, query, or fragment")
    host = parsed.hostname.casefold()
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("WATCH_STT_URL must resolve explicitly to loopback")
        except ValueError as exc:
            raise ValueError("WATCH_STT_URL must use localhost or a loopback IP literal") from exc
    netloc = parsed.netloc
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/audio/transcriptions"):
        transcription_path = base_path
        models_path = base_path.rsplit("/audio/transcriptions", 1)[0] + "/models"
    else:
        prefix = base_path if base_path and base_path != "/" else "/v1"
        if not prefix.endswith("/v1"):
            prefix += "/v1"
        transcription_path = prefix + "/audio/transcriptions"
        models_path = prefix + "/models"
    return (
        urlunsplit((parsed.scheme, netloc, transcription_path, "", "")),
        urlunsplit((parsed.scheme, netloc, models_path, "", "")),
    )


class LoopbackHTTPAdapter:
    name = "local-http"
    requires_audio = True
    is_remote = False

    def __init__(self, *, url: str, model: str, probe_timeout: float = 1.0):
        self.url = url
        self.model = model
        self.probe_timeout = probe_timeout

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        del request
        try:
            _endpoint, models_endpoint = _loopback_endpoint(self.url)
        except ValueError:
            return AdapterAvailability(False, "non_loopback_url", "local HTTP URL rejected")
        try:
            with urlopen(Request(models_endpoint, method="GET"), timeout=self.probe_timeout):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code not in {401, 403, 404, 405}:
                return AdapterAvailability(False, "local_http_unavailable")
        except (urllib.error.URLError, TimeoutError, OSError):
            return AdapterAvailability(False, "local_http_unavailable")
        return AdapterAvailability(True)

    def _transcribe_one(self, request: TranscriptionRequest, chunk: AudioChunk) -> list[dict]:
        endpoint, _models = _loopback_endpoint(self.url)
        fields = {"model": self.model, "response_format": "verbose_json", "temperature": "0"}
        if request.language != "auto":
            fields["language"] = request.language
        body, boundary = whisper.build_multipart(fields, chunk.path)
        http_request = Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "watch-skill/1.0 (loopback-transcription)",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=request.timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"local transcription HTTP {exc.code}") from None
        try:
            return whisper.segments_from_response(json.loads(payload))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("local transcription returned invalid JSON") from exc

    def transcribe(self, request: TranscriptionRequest, receipts: ChunkReceiptStore) -> TranscriptResult:
        return _run_chunked(
            request,
            receipts,
            adapter=self.name,
            model=self.model,
            transcribe_one=lambda chunk: self._transcribe_one(request, chunk),
            remote=False,
        )


class YapAdapter:
    name = "yap"
    requires_audio = True
    is_remote = False

    def __init__(self, *, executable: str = "yap"):
        self.executable = executable

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        del request
        if platform.system() != "Darwin":
            return AdapterAvailability(False, "yap_unsupported_platform")
        resolved = shutil.which(self.executable)
        if resolved is None:
            return AdapterAvailability(False, "yap_not_installed")
        return AdapterAvailability(True)

    def _transcribe_one(self, request: TranscriptionRequest, chunk: AudioChunk) -> list[dict]:
        command = [self.executable, "transcribe", str(chunk.path), "--vtt"]
        if request.language != "auto":
            command += ["--locale", request.language]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request.timeout,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError("YAP did not return timestamped output")
        output = request.work_dir / "yap" / f"chunk_{chunk.index:03d}.vtt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.stdout, encoding="utf-8")
        try:
            return parse_subtitle(output, strict=True)
        finally:
            try:
                output.unlink()
            except OSError:
                pass

    def transcribe(self, request: TranscriptionRequest, receipts: ChunkReceiptStore) -> TranscriptResult:
        return _run_chunked(
            request,
            receipts,
            adapter=self.name,
            model="apple-speech",
            transcribe_one=lambda chunk: self._transcribe_one(request, chunk),
            remote=False,
        )


class CloudWhisperAdapter:
    requires_audio = True
    is_remote = True

    def __init__(self, backend: str):
        if backend not in {"groq", "openai"}:
            raise ValueError("cloud transcription backend must be groq or openai")
        self.name = backend
        self.model = whisper.GROQ_MODEL if backend == "groq" else whisper.OPENAI_MODEL

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        if not request.allow_remote:
            return AdapterAvailability(False, "remote_not_authorized")
        backend, key = whisper.load_api_key(self.name)
        if backend != self.name or not key:
            return AdapterAvailability(False, "cloud_key_unavailable")
        return AdapterAvailability(True)

    def _transcribe_one(self, request: TranscriptionRequest, chunk: AudioChunk) -> list[dict]:
        backend, key = whisper.load_api_key(self.name)
        if backend != self.name or not key:
            raise RuntimeError("cloud key unavailable")
        return whisper.transcribe_file(
            self.name,
            key,
            chunk.path,
            max_attempts=1,
            language=request.language,
        )

    def transcribe(self, request: TranscriptionRequest, receipts: ChunkReceiptStore) -> TranscriptResult:
        return _run_chunked(
            request,
            receipts,
            adapter=self.name,
            model=self.model,
            transcribe_one=lambda chunk: self._transcribe_one(request, chunk),
            remote=True,
        )
