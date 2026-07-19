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
from urllib.request import HTTPRedirectHandler, Request, build_opener

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
    # R2c: audio-preparation caveats (hard_cut boundaries) surface on every
    # adapter's result so the watch report can propagate them.
    warnings: list[str] = list(getattr(request.prepared_audio, "warnings", ()))
    started = time.monotonic()

    silent_chunks = 0
    for chunk in request.prepared_audio.chunks:
        if getattr(chunk, "silent", False):
            # Classified at the chunk layer: skipped, not failed, never cached.
            # A silent chunk must never suppress speech elsewhere in the file.
            silent_chunks += 1
            continue
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
        last_error: BaseException | None = None
        for _attempt in range(request.max_attempts):
            try:
                chunk_values = transcribe_one(chunk)
                if chunk_values:
                    break
            except (Exception, SystemExit) as exc:
                # Keep the cause: "unavailable after bounded retries" alone gives
                # no way to tell a timeout from a missing binary from bad audio.
                last_error = exc
                chunk_values = None
        if not chunk_values:
            failed += 1
            detail = type(last_error).__name__ if last_error else "no output"
            warnings.append(
                f"chunk {chunk.index + 1} unavailable after bounded retries ({detail})"
            )
            continue
        # Validate BEFORE caching: a malformed value crashing here used to
        # happen after receipts.put, so the poisoned cache made every rerun
        # crash identically (L6 review finding).
        try:
            built = _local_segments(
                chunk_values,
                chunk=chunk,
                adapter=adapter,
                model=model,
                language=request.language,
            )
        except (TypeError, ValueError) as exc:
            failed += 1
            warnings.append(
                f"chunk {chunk.index + 1} produced invalid segments ({type(exc).__name__})"
            )
            continue
        processed += 1
        try:
            receipts.put(adapter, model, request.language, chunk, chunk_values)
        except OSError as exc:
            # A receipt is a resume optimization, not the product. A full disk
            # used to abort the adapter here and discard every chunk already
            # transcribed; losing the receipt is strictly cheaper than losing
            # the work.
            warnings.append(f"receipt not stored ({type(exc).__name__}); transcription continues")
        segments.extend(built)

    # Receipts are flushed in batches, so the tail must be persisted explicitly
    # or the last <5 chunks would be re-transcribed on resume.
    try:
        receipts.flush()
    except OSError as exc:
        warnings.append(f"receipt not stored ({type(exc).__name__}); transcription continues")

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
            "silent_chunks": silent_chunks,
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


# yap takes an Apple locale and rejects a bare language code outright:
#   $ yap transcribe a.wav --locale en
#   Locale "en" is not supported. Supported locales: ["fr_FR", ... "en_US" ...]
# and it exits 0 while doing so. WATCH_LANGUAGE=en is the most natural thing a
# user would set, so map bare codes onto yap's default region for that language.
_YAP_DEFAULT_REGION = {
    "en": "en_US", "fr": "fr_FR", "de": "de_DE", "it": "it_IT", "es": "es_ES",
    "pt": "pt_BR", "ko": "ko_KR", "ja": "ja_JP", "zh": "zh_CN", "yue": "yue_CN",
}


def _yap_locale(language: str) -> str:
    """Normalize a WATCH_LANGUAGE value to an Apple locale yap will accept."""
    value = language.strip().replace("-", "_")
    if "_" in value:  # already regioned, e.g. en-GB -> en_GB
        base, _, region = value.partition("_")
        return f"{base.lower()}_{region.upper()}"
    return _YAP_DEFAULT_REGION.get(value.lower(), value)


def _whisper_language(language: str) -> str | None:
    """Normalize WATCH_LANGUAGE for the openai-whisper CLI, or None to autodetect.

    Exactly inverse to yap: whisper takes a bare code ('en') and rejects locale
    forms ('en-US'), while yap rejects bare codes and demands the locale. One
    WATCH_LANGUAGE value has to satisfy both, so each adapter normalizes on the
    way out rather than constraining what the user may configure.
    """
    if language.strip().lower() == "auto":
        return None
    base = language.strip().replace("_", "-").split("-")[0].lower()
    return base if len(base) == 2 else None


class _NoRedirects(HTTPRedirectHandler):
    """Refuse every 3xx.

    The loopback URL is validated to point at localhost, but urlopen follows
    redirects by default, so a compromised or malicious machine-local server
    could answer 302 and send the audio to an external host. That would silently
    break the skill's central guarantee: audio never leaves the machine without
    explicit consent. Validating the URL and then following wherever it points
    is not a guarantee at all.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(
            f"refusing HTTP {code} redirect from local STT server to {newurl!r}"
        )


# Redirect-refusing opener, used for every loopback request.
_LOOPBACK_OPENER = build_opener(_NoRedirects())


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
            with _LOOPBACK_OPENER.open(Request(models_endpoint, method="GET"), timeout=self.probe_timeout):
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
            with _LOOPBACK_OPENER.open(http_request, timeout=request.timeout) as response:
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
            command += ["--locale", _yap_locale(request.language)]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request.timeout,
        )
        # yap exits 0 even when it rejects the locale, printing an error where the
        # captions should be. Trusting the exit code would hand that error text to
        # the parser as if it were a transcript.
        if result.returncode != 0 or "WEBVTT" not in (result.stdout or ""):
            detail = (result.stdout or result.stderr or "").strip().splitlines()
            hint = f": {detail[0][:80]}" if detail else ""
            raise RuntimeError(f"YAP did not return timestamped output{hint}")
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


class WhisperCliAdapter:
    """A real speech model running on this machine, via the `openai-whisper` CLI.

    Closes the gap that pushed Linux users to the cloud: local-http needs a
    server they must run themselves, and yap is macOS-only, so a Linux box with
    no server had no local option at all and fell through to cloud Whisper --
    quietly contradicting the local-first promise. No daemon, no network, just a
    subprocess. Detected, never installed (`pip install openai-whisper`).

    `small` by default: on CPU it stays usable, where medium/large cost several
    times the wall time for marginal gains without a GPU.
    """

    name = "whisper-cli"
    requires_audio = True
    is_remote = False

    def __init__(
        self,
        *,
        executable: str = "whisper",
        model: str = "small",
        vad: bool = True,
        vad_model_path: str = "",
    ):
        self.executable = executable
        self.model = model
        self.vad = vad
        self.vad_model_path = vad_model_path
        # Set after a --vad invocation fails: VAD is best-effort, so one
        # failure disables it for the rest of this adapter's lifetime.
        self._vad_withdrawn = False

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        del request
        if shutil.which(self.executable) is None:
            return AdapterAvailability(False, "whisper_cli_not_installed")
        return AdapterAvailability(True)

    def _vad_args(self) -> list[str]:
        """WITHDRAWN (1.2.1). The 1.2.0 tier composed whisper.cpp flags
        (--vad/--vad-model + a ggml Silero model) but this adapter invokes the
        pip openai-whisper CLI, which rejects them — the feature could never
        engage, and the fail-open catch hid that permanently (found by the L6
        review, three independent angles). Config keys are retained as
        documented-future; VAD returns only when composed against a CLI that
        actually supports it (capability-probed, not assumed)."""
        return []

    def _parse_json_output(self, output: Path) -> list[dict]:
        data = json.loads(output.read_text(encoding="utf-8"))
        # Delegate to the shared normalizer so cloud and CLI reject malformed
        # cues identically (v1.2.1 validity drop: end < start / start < 0 cues
        # are dropped inside the per-chunk retry boundary — not later in
        # _local_segments where a ValueError would kill the whole adapter and
        # poison receipts). Segments only: the CLI JSON's top-level "text"
        # must NOT trigger the cloud fallback that fabricates a 0.0-0.0
        # segment — a chunk with no valid cues stays a failed chunk here.
        return whisper.segments_from_response({"segments": data.get("segments")})

    def _transcribe_one(self, request: TranscriptionRequest, chunk: AudioChunk) -> list[dict]:
        out_dir = request.work_dir / "whisper-cli"
        out_dir.mkdir(parents=True, exist_ok=True)
        # json, not srt: it is the only whisper CLI output format that carries
        # word-level timestamps (R2b), and parsing it is no harder than srt.
        output = out_dir / f"{chunk.path.stem}.json"
        language = _whisper_language(request.language)

        def attempt(extra_args: list[str]) -> list[dict]:
            # A killed prior run can leave output behind. Delete it first, so
            # the file's presence is a signal about THIS invocation, not a fossil.
            if output.exists():
                output.unlink()
            command = [
                self.executable, str(chunk.path),
                "--model", self.model,
                "--output_format", "json",
                "--output_dir", str(out_dir),
                "--word_timestamps", "True",
                *extra_args,
            ]
            if language:
                command += ["--language", language]
            subprocess.run(command, capture_output=True, text=True, timeout=request.timeout)
            # The whisper CLI can exit 0 having produced nothing (its internal
            # ffmpeg failing on the input, for one). The output file is the only
            # honest success signal; the return code is not. Same trap as yap,
            # which exits 0 while rejecting a locale.
            if not output.is_file():
                raise RuntimeError("whisper CLI did not produce an output file")
            try:
                return self._parse_json_output(output)
            except (OSError, UnicodeError, ValueError) as exc:
                raise RuntimeError("whisper CLI produced invalid JSON output") from exc
            finally:
                try:
                    output.unlink()
                except OSError:
                    pass

        return attempt([])

    def transcribe(self, request: TranscriptionRequest, receipts: ChunkReceiptStore) -> TranscriptResult:
        return _run_chunked(
            request,
            receipts,
            adapter=self.name,
            model=self.model,
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
