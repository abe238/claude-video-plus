#!/usr/bin/env python3
"""Deep, normalized transcription Interface for every transcript Adapter.

The public integration point is :func:`transcribe`.  It returns a
``TranscriptResult`` for success, partial output, optional unavailability, or a
stable failure without exposing backend-specific exceptions to callers.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

import whisper
from config import get_transcription_config
from transcribe import filter_range
from transcription_chunks import ChunkReceiptStore, PreparedAudio, prepare_audio


TRANSCRIPT_STATES = frozenset({"success", "degraded", "partial", "unavailable", "fatal", "no_speech"})
USABLE_STATES = frozenset({"success", "degraded", "partial"})


@dataclass(frozen=True)
class TranscriptWord:
    """One word with absolute timestamps. Best-effort: absent on most backends."""

    word: str
    start: float
    end: float


def _parse_words(value: object, *, offset: float) -> tuple[TranscriptWord, ...]:
    """Coerce an optional backend 'words' list, shifting by the segment offset.

    Entry validation delegates to whisper._clean_words — ONE rule set shared by
    the cloud and CLI word paths (drop empty text, non-numeric, start < 0,
    end < start). Fail-open: malformed entries are dropped, never raised —
    words are an enrichment, and a bad word list must not cost the segment."""
    words: list[TranscriptWord] = []
    for entry in whisper._clean_words(value):
        start = round(entry["start"] + offset, 3)
        end = round(entry["end"] + offset, 3)
        if start < 0 or end < start:  # invariant guard after the offset shift
            continue
        words.append(TranscriptWord(word=entry["word"], start=start, end=end))
    return tuple(words)


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    language: str = "auto"
    adapter: str = "unknown"
    model: str | None = None
    confidence: float | None = None
    warnings: tuple[str, ...] = ()
    # R2b: word-level timestamps, absent-tolerant (empty on backends without them).
    words: tuple[TranscriptWord, ...] = ()

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("transcript segment timestamps are invalid")
        if not self.text.strip():
            raise ValueError("transcript segment text is empty")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("transcript confidence must be between zero and one")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
        *,
        language: str = "auto",
        adapter: str = "unknown",
        model: str | None = None,
        offset: float = 0.0,
    ) -> "TranscriptSegment":
        return cls(
            start=round(float(value.get("start") or 0.0) + offset, 3),
            end=round(float(value.get("end") or 0.0) + offset, 3),
            text=str(value.get("text") or "").strip(),
            language=str(value.get("language") or language),
            adapter=str(value.get("adapter") or adapter),
            model=str(value.get("model") or model) if value.get("model") or model else None,
            confidence=(
                float(value["confidence"])
                if value.get("confidence") is not None
                else None
            ),
            warnings=(
                (str(value["warnings"]),)
                if isinstance(value.get("warnings"), str)
                else tuple(str(item) for item in value.get("warnings") or ())
            ),
            words=_parse_words(value.get("words"), offset=offset),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TranscriptAttempt:
    adapter: str
    state: str
    elapsed_ms: int = 0
    model: str | None = None
    failure_code: str | None = None
    detail: str | None = None
    processed_chunks: int = 0
    reused_chunks: int = 0

    def __post_init__(self) -> None:
        if self.state not in TRANSCRIPT_STATES:
            raise ValueError(f"unknown transcript attempt state: {self.state}")


@dataclass(frozen=True)
class TranscriptResult:
    state: str
    segments: tuple[TranscriptSegment, ...] = ()
    adapter: str | None = None
    model: str | None = None
    language: str = "auto"
    warnings: tuple[str, ...] = ()
    attempts: tuple[TranscriptAttempt, ...] = ()
    fallback_reason: str | None = None
    failure_code: str | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in TRANSCRIPT_STATES:
            raise ValueError(f"unknown transcript result state: {self.state}")
        if self.state in {"success", "degraded"} and not self.segments:
            raise ValueError(f"{self.state} transcript result requires segments")
        if self.state == "fatal" and not self.failure_code:
            raise ValueError("fatal transcript result requires a stable failure code")

    @property
    def usable(self) -> bool:
        return self.state in USABLE_STATES and bool(self.segments)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "segments": [segment.to_dict() for segment in self.segments],
            "adapter": self.adapter,
            "model": self.model,
            "language": self.language,
            "warnings": list(self.warnings),
            "attempts": [asdict(attempt) for attempt in self.attempts],
            "fallback_reason": self.fallback_reason,
            "failure_code": self.failure_code,
            "diagnostics": dict(self.diagnostics),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


@dataclass(frozen=True)
class AdapterAvailability:
    available: bool
    failure_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class TranscriptionRequest:
    media_path: Path
    work_dir: Path
    native_segments: tuple[Mapping[str, object] | TranscriptSegment, ...] = ()
    native_language: str = "auto"
    start_seconds: float | None = None
    end_seconds: float | None = None
    language: str = "auto"
    adapter_order: tuple[str, ...] = ("local-http", "yap", "groq", "openai")
    explicit_adapter: str | None = None
    allow_remote: bool = False
    require_complete: bool = True
    max_attempts: int = 2
    timeout: float = 300.0
    config: Mapping[str, object] = field(default_factory=dict)
    prepared_audio: PreparedAudio | None = None
    # One remote-cost budget for the WHOLE run: Groq and OpenAI (and every
    # retry) draw from the same pool, so provider fallback cannot double-spend.
    # dataclasses.replace() keeps the same ledger object across request copies.
    remote_ledger: whisper.RemoteCostLedger = field(default_factory=whisper.RemoteCostLedger)

    def __post_init__(self) -> None:
        if self.start_seconds is not None and self.start_seconds < 0:
            raise ValueError("range start must be non-negative")
        if (
            self.end_seconds is not None
            and self.start_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("range end must be greater than range start")
        if not 1 <= self.max_attempts <= 4:
            raise ValueError("max_attempts must be between one and four")


@runtime_checkable
class TranscriptAdapter(Protocol):
    name: str
    requires_audio: bool
    is_remote: bool

    def probe(self, request: TranscriptionRequest) -> AdapterAvailability:
        """Return availability without performing unsafe or remote work."""

    def transcribe(
        self,
        request: TranscriptionRequest,
        receipts: ChunkReceiptStore,
    ) -> TranscriptResult:
        """Execute this Adapter and return only normalized states/segments."""


def _native_result(request: TranscriptionRequest) -> TranscriptResult | None:
    if not request.native_segments:
        return None
    mappings = [
        segment.to_dict() if isinstance(segment, TranscriptSegment) else dict(segment)
        for segment in request.native_segments
    ]
    filtered = filter_range(mappings, request.start_seconds, request.end_seconds)
    segments = tuple(
        TranscriptSegment.from_mapping(
            segment,
            language=request.native_language,
            adapter="native-captions",
        )
        for segment in filtered
        if str(segment.get("text") or "").strip()
    )
    if not segments:
        return None
    return TranscriptResult(
        state="success",
        segments=segments,
        adapter="native-captions",
        language=request.native_language,
        attempts=(TranscriptAttempt(adapter="native-captions", state="success"),),
        diagnostics={"remote_transmission": False, "range_applied": bool(request.start_seconds or request.end_seconds)},
    )


def build_default_adapters(config: Mapping[str, object]) -> dict[str, TranscriptAdapter]:
    # Imported after the contract definitions so Adapter implementations can
    # import this Module without a circular initialization dependency.
    from transcription_adapters import (  # noqa: PLC0415
        CloudWhisperAdapter,
        LoopbackHTTPAdapter,
        SidecarAdapter,
        WhisperCliAdapter,
        YapAdapter,
    )

    return {
        "sidecar": SidecarAdapter(),
        "local-http": LoopbackHTTPAdapter(
            url=str(config.get("url") or ""),
            model=str(config.get("model") or ""),
            probe_timeout=float(config.get("probe_timeout") or 1.0),
        ),
        "yap": YapAdapter(executable=str(config.get("yap_path") or "yap")),
        "whisper-cli": WhisperCliAdapter(
            executable=str(config.get("whisper_cli_path") or "whisper"),
            model=str(config.get("whisper_cli_model") or "small"),
            vad=bool(config.get("vad", True)),
            vad_model_path=str(config.get("vad_model_path") or ""),
        ),
        "groq": CloudWhisperAdapter("groq"),
        "openai": CloudWhisperAdapter("openai"),
    }


def transcript_cost_limited(result: "TranscriptResult | None") -> bool:
    """THE predicate for rendering remote-cost guidance: the budget tripped
    AND the transcript is incomplete. A complete transcript rescued by a later
    adapter renders no guidance — there is nothing left to re-run for."""
    if result is None or result.state not in ("partial", "unavailable"):
        return False
    return result.failure_code == "remote_cost_limit_exceeded" or any(
        attempt.failure_code == "remote_cost_limit_exceeded" for attempt in result.attempts
    )


def _aggregate_run_truth(
    result: TranscriptResult,
    request: TranscriptionRequest,
    run_loop_indices: frozenset[int] | set[int] = frozenset(),
) -> TranscriptResult:
    """Fold run-level facts into the result an adapter produced.

    A later local adapter knows nothing about the remote sends that came
    before it: without this fold, a local fallback reports
    ``remote_transmission: False`` after bytes already left the machine, and a
    local partial rewrites ``remote_cost_limit_exceeded`` into
    ``incomplete_chunks`` — hiding that the transcript is incomplete because
    the run's remote budget tripped and a --start/--end re-run would fix it.
    """
    diagnostics = dict(result.diagnostics)
    if request.remote_ledger.attempts > 0:
        diagnostics["remote_transmission"] = True
    union = set(run_loop_indices) | set(diagnostics.get("loop_chunk_indices") or ())
    if union:
        # Chunk IDENTITIES, not per-adapter counts: the same chunk looping
        # under two fallback adapters is ONE affected chunk, and a later
        # adapter's result must not erase earlier detections this run.
        diagnostics["loop_detected_chunks"] = len(union)
        diagnostics["loop_chunk_indices"] = sorted(union)
    cost_limited = any(
        attempt.failure_code == "remote_cost_limit_exceeded" for attempt in result.attempts
    )
    warnings = result.warnings
    failure_code = result.failure_code
    if cost_limited and result.state == "partial":
        # A COMPLETE transcript from a later adapter needs no guidance; an
        # incomplete one exists BECAUSE the budget tripped — say so at run
        # level (per-adapter attempt rows keep their own honest codes).
        failure_code = "remote_cost_limit_exceeded"
        if whisper.REMOTE_COST_GUIDANCE not in warnings:
            warnings = warnings + (whisper.REMOTE_COST_GUIDANCE,)
    return replace(
        result, diagnostics=diagnostics, warnings=warnings, failure_code=failure_code
    )


class TranscriptionPipeline:
    """Ordered Adapter orchestration with privacy-preserving short circuits."""

    def __init__(self, adapters: Mapping[str, TranscriptAdapter] | None = None):
        self._adapters = dict(adapters or {})

    def run(self, request: TranscriptionRequest) -> TranscriptResult:
        native = _native_result(request)
        if native is not None:
            return native

        adapters = self._adapters or build_default_adapters(request.config)
        order: list[str] = ["sidecar"]
        if request.explicit_adapter and request.explicit_adapter != "auto":
            requested_order = () if request.explicit_adapter == "sidecar" else (request.explicit_adapter,)
        else:
            requested_order = request.adapter_order
        order.extend(name for name in requested_order if name != "sidecar")
        unknown = [name for name in order if name not in adapters]
        if unknown:
            return TranscriptResult(
                state="fatal",
                language=request.language,
                failure_code="invalid_adapter",
                warnings=(f"unknown transcript Adapter: {unknown[0]}",),
            )

        receipts = ChunkReceiptStore(
            request.work_dir / "transcription-receipts.json",
            enabled=bool(request.config.get("receipts", True)),
        )
        attempts: list[TranscriptAttempt] = []
        partial: TranscriptResult | None = None
        prepared = request.prepared_audio
        run_loop_indices: set[int] = set()

        for name in order:
            adapter = adapters[name]
            started = time.monotonic()
            if adapter.is_remote and not request.allow_remote:
                attempts.append(
                    TranscriptAttempt(
                        adapter=name,
                        state="unavailable",
                        failure_code="remote_not_authorized",
                        detail="remote transcription requires explicit authorization",
                    )
                )
                continue
            if adapter.is_remote and request.remote_ledger.exhausted:
                # Pipeline-level, not probe-level: a custom remote adapter that
                # never checks the ledger must STILL be refused — no probe, no
                # send, nothing after the run's budget is spent.
                attempts.append(
                    TranscriptAttempt(
                        adapter=name,
                        state="unavailable",
                        failure_code="remote_cost_limit_exceeded",
                        detail="remote cost budget spent earlier in this run",
                    )
                )
                continue

            try:
                availability = adapter.probe(request)
            except (Exception, SystemExit) as exc:
                availability = AdapterAvailability(
                    False,
                    "adapter_probe_failed",
                    type(exc).__name__,
                )
            if not availability.available:
                attempts.append(
                    TranscriptAttempt(
                        adapter=name,
                        state="unavailable",
                        elapsed_ms=round((time.monotonic() - started) * 1000),
                        failure_code=availability.failure_code or "adapter_unavailable",
                        detail=availability.detail,
                    )
                )
                continue

            if adapter.requires_audio and prepared is None:
                # Lazy (L6 review): probes are local and upload nothing, so
                # preparing AFTER a successful probe keeps the zero-work path on
                # machines with no available backend, while the silence gate
                # below still runs BEFORE transcribe — the no-upload guarantee
                # is enforced where upload actually happens.
                try:
                    prepared = prepare_audio(
                        request.media_path,
                        request.work_dir / "transcription-audio",
                        start_seconds=request.start_seconds,
                        end_seconds=request.end_seconds,
                    )
                    request = replace(request, prepared_audio=prepared)
                except (OSError, RuntimeError, ValueError) as exc:
                    return TranscriptResult(
                        state="fatal",
                        language=request.language,
                        attempts=tuple(attempts),
                        failure_code="audio_preparation_failed",
                        warnings=(f"audio preparation failed: {type(exc).__name__}",),
                    )
            if (
                adapter.requires_audio
                and prepared is not None
                and prepared.all_silent
                and bool(request.config.get("no_speech_gate", True))
            ):
                return TranscriptResult(
                    state="no_speech",
                    language=request.language,
                    attempts=tuple(attempts),
                    warnings=("no speech detected in the audio",),
                    diagnostics={"silent_chunks": len(prepared.chunks)},
                )

            try:
                result = adapter.transcribe(request, receipts)
            except (Exception, SystemExit) as exc:
                attempts.append(
                    TranscriptAttempt(
                        adapter=name,
                        state="unavailable",
                        elapsed_ms=round((time.monotonic() - started) * 1000),
                        failure_code="adapter_execution_failed",
                        detail=type(exc).__name__,
                    )
                )
                continue
            run_loop_indices |= set(result.diagnostics.get("loop_chunk_indices") or ())
            result_attempts = list(result.attempts)
            if not result_attempts:
                result_attempts.append(
                    TranscriptAttempt(
                        adapter=name,
                        state=result.state,
                        elapsed_ms=round((time.monotonic() - started) * 1000),
                        model=result.model,
                        failure_code=result.failure_code,
                    )
                )
            attempts.extend(result_attempts)

            if result.state in {"success", "degraded"} and result.segments:
                prior_failures = [attempt.adapter for attempt in attempts[:-len(result_attempts)] if attempt.state != "success"]
                state = "degraded" if prior_failures else result.state
                fallback = result.fallback_reason
                if prior_failures and not fallback:
                    fallback = "earlier Adapters unavailable: " + ", ".join(prior_failures)
                return _aggregate_run_truth(
                    replace(result, state=state, attempts=tuple(attempts), fallback_reason=fallback),
                    request,
                    run_loop_indices,
                )
            if result.state == "partial" and result.segments:
                partial = replace(result, attempts=tuple(attempts))
                if not request.require_complete:
                    return _aggregate_run_truth(partial, request, run_loop_indices)
            if result.state == "fatal":
                return _aggregate_run_truth(
                    replace(result, attempts=tuple(attempts)), request, run_loop_indices
                )

        if partial is not None:
            # Re-attach the FULL attempt list: locals run before cloud, so a
            # stored local partial predates the remote attempts (and any cost
            # trip) that happened after it.
            return _aggregate_run_truth(
                replace(partial, attempts=tuple(attempts)), request, run_loop_indices
            )
        cost_limited = any(
            attempt.failure_code == "remote_cost_limit_exceeded" for attempt in attempts
        )
        unavailable_diagnostics: dict[str, object] = {
            "remote_transmission": request.remote_ledger.attempts > 0,
        }
        if run_loop_indices:
            # The all-unavailable path must not drop detections either.
            unavailable_diagnostics["loop_detected_chunks"] = len(run_loop_indices)
            unavailable_diagnostics["loop_chunk_indices"] = sorted(run_loop_indices)
        return TranscriptResult(
            state="unavailable",
            language=request.language,
            attempts=tuple(attempts),
            # Never rewrite the cost limit to a generic code: the report's
            # --start/--end guidance keys off it, and "transcript_unavailable"
            # would hide that the user can fix this with a bound or a range.
            failure_code="remote_cost_limit_exceeded" if cost_limited else "transcript_unavailable",
            warnings=(
                (whisper.REMOTE_COST_GUIDANCE,)
                if cost_limited
                else ("no transcript Adapter produced usable timestamped output",)
            ),
            diagnostics=unavailable_diagnostics,
        )


def transcribe(
    media_path: str | Path,
    work_dir: str | Path,
    *,
    native_segments: Sequence[Mapping[str, object] | TranscriptSegment] = (),
    native_language: str = "auto",
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    adapter: str | None = None,
    allow_remote: bool | None = None,
    require_complete: bool = True,
    config_overrides: Mapping[str, object] | None = None,
    adapters: Mapping[str, TranscriptAdapter] | None = None,
) -> TranscriptResult:
    """Transcribe through the normalized Interface without host-specific state."""
    config = get_transcription_config(**dict(config_overrides or {}))
    request = TranscriptionRequest(
        media_path=Path(media_path).expanduser().resolve(),
        work_dir=Path(work_dir).expanduser().resolve(),
        native_segments=tuple(native_segments),
        native_language=native_language,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        language=str(config["language"]),
        adapter_order=tuple(config["order"]),
        explicit_adapter=adapter,
        allow_remote=bool(config["allow_remote"] if allow_remote is None else allow_remote),
        require_complete=require_complete,
        max_attempts=int(config["max_attempts"]),
        timeout=float(config["timeout"]),
        config=config,
    )
    return TranscriptionPipeline(adapters).run(request)


def transcript_status_label(result: "TranscriptResult") -> str | None:
    """Report wording: silence is a finding, not a failure. Returns a label for
    states that need distinct phrasing; None keeps the existing message path."""
    if result is not None and getattr(result, "state", None) == "no_speech":
        return "no speech detected in the audio"
    return None


def transcription_diagnostics(**config_overrides: object) -> dict[str, object]:
    """Machine-readable, secret-free option mapping for host diagnostics."""
    try:
        config = get_transcription_config(**config_overrides)
    except ValueError as exc:
        return {"state": "fatal", "failure_code": "invalid_config", "warnings": [str(exc)]}
    return {
        "state": "success",
        "order": list(config["order"]),
        "language": config["language"],
        "loop_detect": bool(config.get("loop_detect", True)),
        "local_http": {
            "configured": bool(config["url"]),
            "loopback_required": True,
            "model": config["model"],
        },
        "yap": {"executable": Path(str(config["yap_path"])).name, "auto_install": False},
        "cloud": {"authorized": bool(config["allow_remote"]), "headers_redacted": True},
        "max_attempts": config["max_attempts"],
        "receipts": bool(config["receipts"]),
    }
