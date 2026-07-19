#!/usr/bin/env python3
"""Shared /watch configuration helpers."""
from __future__ import annotations

import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "watch"
CONFIG_FILE = CONFIG_DIR / ".env"

DEFAULT_DETAIL = "balanced"

DETAILS = {"transcript", "efficient", "balanced", "token-burner"}

# Every local adapter is tried before any cloud adapter. whisper-cli sits last
# among the local ones: it is the heaviest (it loads a model per chunk) but it is
# the only local option that exists on a bare Linux box, where local-http needs a
# server the user runs themselves and yap is macOS-only.
DEFAULT_STT_ORDER = ("local-http", "yap", "whisper-cli", "groq", "openai")
STT_ADAPTERS = frozenset(DEFAULT_STT_ORDER)
DEFAULT_STT_URL = "http://127.0.0.1:8082"
DEFAULT_STT_MODEL = "Systran/faster-whisper-medium"
DEFAULT_WHISPER_CLI_MODEL = "small"
DEFAULT_LANGUAGE = "auto"
# R2a-2: Silero VAD for whisper-cli only. The model is DETECTED at this path,
# never downloaded automatically — a future release may add a pinned-SHA
# download. WATCH_VAD=off disables even when the file exists.
DEFAULT_VAD_MODEL_PATH = str(CONFIG_DIR / "models" / "ggml-silero-v5.1.2.bin")


def read_env_file(path: Path | None = None) -> dict[str, str]:
    if path is None:
        path = CONFIG_FILE
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # Strip an inline comment (a '#' preceded by whitespace) from an
            # unquoted value. Without this, `WATCH_DETAIL=balanced  # note`
            # parses as "balanced  # note", fails validation, and silently
            # falls back to the default. Keeps '#' inside quotes / API keys.
            for i, ch in enumerate(value):
                if ch == "#" and i > 0 and value[i - 1] in " \t":
                    value = value[:i].rstrip()
                    break
        values[key.strip()] = value
    return values


def get_config() -> dict[str, object]:
    file_values = read_env_file()

    detail = (
        os.environ.get("WATCH_DETAIL")
        or file_values.get("WATCH_DETAIL")
        or DEFAULT_DETAIL
    )
    if detail not in DETAILS:
        detail = DEFAULT_DETAIL

    return {
        "detail": detail,
        "config_file": str(CONFIG_FILE),
    }


def _config_value(
    name: str,
    file_values: dict[str, str],
    overrides: dict[str, object],
    default: object = None,
) -> object:
    """Resolve invocation override > environment > user config > default."""
    if name in overrides and overrides[name] is not None:
        return overrides[name]
    if name in os.environ:
        return os.environ[name]
    if name in file_values:
        return file_values[name]
    return default


def _bool_value(value: object, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be true or false")


def get_transcription_config(**overrides: object) -> dict[str, object]:
    """Return the host-independent transcription configuration.

    This is separate from :func:`get_config` so the existing detail-mode
    Interface remains stable while P11-P18 land behind a new transcription
    seam.  Keys and authorization headers are deliberately not returned.
    """
    file_values = read_env_file()

    raw_order = _config_value(
        "WATCH_STT_ORDER", file_values, overrides, ",".join(DEFAULT_STT_ORDER)
    )
    if isinstance(raw_order, (tuple, list)):
        order = tuple(str(item).strip().lower() for item in raw_order if str(item).strip())
    else:
        order = tuple(part.strip().lower() for part in str(raw_order).split(",") if part.strip())
    if not order:
        raise ValueError("WATCH_STT_ORDER must name at least one Adapter")
    unknown = sorted(set(order) - STT_ADAPTERS)
    if unknown:
        raise ValueError(f"WATCH_STT_ORDER contains unknown Adapter(s): {', '.join(unknown)}")
    if len(order) != len(set(order)):
        raise ValueError("WATCH_STT_ORDER must not contain duplicate Adapters")

    language = str(
        _config_value("WATCH_LANGUAGE", file_values, overrides, DEFAULT_LANGUAGE)
    ).strip() or DEFAULT_LANGUAGE
    stt_url = str(
        _config_value("WATCH_STT_URL", file_values, overrides, DEFAULT_STT_URL)
    ).strip()
    stt_model = str(
        _config_value("WATCH_STT_MODEL", file_values, overrides, DEFAULT_STT_MODEL)
    ).strip() or DEFAULT_STT_MODEL
    yap_path = str(_config_value("WATCH_YAP_PATH", file_values, overrides, "yap")).strip() or "yap"
    whisper_cli_path = str(
        _config_value("WATCH_WHISPER_CLI_PATH", file_values, overrides, "whisper")
    ).strip() or "whisper"
    whisper_cli_model = str(
        _config_value("WATCH_WHISPER_CLI_MODEL", file_values, overrides, DEFAULT_WHISPER_CLI_MODEL)
    ).strip() or DEFAULT_WHISPER_CLI_MODEL

    try:
        # 600s, not 300s. A chunk is ~3.3 min of audio. Apple Silicon
        # faster-whisper does one in ~93s (0.46x realtime, measured), but
        # CPU-only openai-whisper -- the hardware whisper-cli exists for -- runs
        # slower than realtime, so 300s would time out on every chunk. This is a
        # ceiling, not a wait: a fast backend still returns as soon as it is done.
        timeout = float(_config_value("WATCH_STT_TIMEOUT", file_values, overrides, 600.0))
        probe_timeout = float(
            _config_value("WATCH_STT_PROBE_TIMEOUT", file_values, overrides, 1.0)
        )
        max_attempts = int(_config_value("WATCH_STT_MAX_ATTEMPTS", file_values, overrides, 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("transcription timeout/attempt settings must be numeric") from exc
    if timeout <= 0 or probe_timeout <= 0:
        raise ValueError("transcription timeouts must be greater than zero")
    if not 1 <= max_attempts <= 4:
        raise ValueError("WATCH_STT_MAX_ATTEMPTS must be between 1 and 4")

    allow_remote = _bool_value(
        _config_value("WATCH_STT_ALLOW_REMOTE", file_values, overrides, False),
        name="WATCH_STT_ALLOW_REMOTE",
    )
    receipts = _bool_value(
        _config_value("WATCH_STT_RECEIPTS", file_values, overrides, True),
        name="WATCH_STT_RECEIPTS",
    )
    no_speech_gate = _bool_value(
        _config_value("WATCH_NO_SPEECH", file_values, overrides, True),
        name="WATCH_NO_SPEECH",
    )
    vad = _bool_value(
        _config_value("WATCH_VAD", file_values, overrides, True),
        name="WATCH_VAD",
    )
    vad_model_path = str(
        _config_value("WATCH_VAD_MODEL_PATH", file_values, overrides, DEFAULT_VAD_MODEL_PATH)
    ).strip() or DEFAULT_VAD_MODEL_PATH

    return {
        "order": order,
        "url": stt_url,
        "model": stt_model,
        "language": language,
        "yap_path": yap_path,
        "whisper_cli_path": whisper_cli_path,
        "whisper_cli_model": whisper_cli_model,
        "allow_remote": allow_remote,
        "timeout": timeout,
        "probe_timeout": probe_timeout,
        "max_attempts": max_attempts,
        "receipts": receipts,
        "no_speech_gate": no_speech_gate,
        "vad": vad,
        "vad_model_path": vad_model_path,
        "config_file": str(CONFIG_FILE),
    }


def frame_cap(detail: str) -> int | None:
    if detail == "efficient":
        return 50
    if detail == "balanced":
        return 100
    if detail == "token-burner":
        return None
    if detail == "transcript":
        return None
    return 100
