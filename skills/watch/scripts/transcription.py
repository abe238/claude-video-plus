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

from config import get_transcription_config
from transcribe import filter_range
from transcription_chunks import ChunkReceiptStore, PreparedAudio, prepare_audio


TRANSCRIPT_STATES = frozenset({"success", "degraded", "partial", "unavailable", "fatal"})
USABLE_STATES = frozenset({"success", "degraded", "partial"})


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
        ),
        "groq": CloudWhisperAdapter("groq"),
        "openai": CloudWhisperAdapter("openai"),
    }


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
                        warnings=(type(exc).__name__,),
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
                return replace(result, state=state, attempts=tuple(attempts), fallback_reason=fallback)
            if result.state == "partial" and result.segments:
                partial = replace(result, attempts=tuple(attempts))
                if not request.require_complete:
                    return partial
            if result.state == "fatal":
                return replace(result, attempts=tuple(attempts))

        if partial is not None:
            return partial
        return TranscriptResult(
            state="unavailable",
            language=request.language,
            attempts=tuple(attempts),
            failure_code="transcript_unavailable",
            warnings=("no transcript Adapter produced usable timestamped output",),
            diagnostics={"remote_transmission": False},
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
