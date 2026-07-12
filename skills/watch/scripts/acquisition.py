#!/usr/bin/env python3
"""Deep, stdlib-only video acquisition Interface.

The default yt-dlp invocation always runs first.  Only classified, retryable
failures enter the bounded YouTube recovery ladder; attempt records contain no
URLs, cookies, headers, signed query strings, or local browser-profile paths.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit


class FailureClass(str, Enum):
    SABR_CLIENT = "sabr_client"
    HTTP_403 = "http_403"
    HTTP_429 = "http_429"
    NETWORK_TIMEOUT = "network_timeout"
    FORMAT_UNAVAILABLE = "format_unavailable"
    INVALID_SOURCE = "invalid_source"
    LOGIN_REQUIRED = "login_required"
    REGION_LOCKED = "region_locked"
    PRIVATE_OR_DELETED = "private_or_deleted"
    UNSUPPORTED_EXTRACTOR = "unsupported_extractor"
    COOKIE_VALIDATION = "cookie_validation"
    INTEGRITY_REFUSAL = "integrity_refusal"
    UNKNOWN = "unknown"


RETRYABLE_FAILURES = frozenset({
    FailureClass.SABR_CLIENT,
    FailureClass.HTTP_403,
    FailureClass.HTTP_429,
    FailureClass.NETWORK_TIMEOUT,
    FailureClass.FORMAT_UNAVAILABLE,
})

FATHOM_DEFERRED = True
FATHOM_DEFERRED_REASON = (
    "Fathom private-call acquisition is outside v1.0 and has no runtime Adapter"
)
COOKIE_BROWSERS = frozenset({
    "brave", "chrome", "chromium", "edge", "firefox", "opera", "safari",
    "vivaldi", "whale",
})
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_. -]{1,80}$")


@dataclass(frozen=True)
class AcquisitionAttempt:
    strategy: str
    outcome: str
    failure_class: str | None
    exit_code: int
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "outcome": self.outcome,
            "failure_class": self.failure_class,
            "exit_code": self.exit_code,
            "detail": self.detail,
        }


@dataclass
class AcquisitionResult:
    state: str
    media_path: str | None
    subtitle_candidates: list[str]
    selected_subtitle: str | None
    metadata: dict
    source_identity: str
    attempts: list[AcquisitionAttempt] = field(default_factory=list)
    selected_strategy: str | None = None
    warnings: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    failure_class: str | None = None
    downloaded: bool = False

    def as_dict(self) -> dict:
        """Return the normalized result plus legacy keys used by watch.py."""
        return {
            "state": self.state,
            "media_path": self.media_path,
            "video_path": self.media_path,
            "subtitle_candidates": list(self.subtitle_candidates),
            "selected_subtitle": self.selected_subtitle,
            "subtitle_path": self.selected_subtitle,
            "metadata": dict(self.metadata),
            "info": dict(self.metadata),
            "source_identity": self.source_identity,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "selected_strategy": self.selected_strategy,
            "warnings": list(self.warnings),
            "fallback_reason": self.fallback_reason,
            "failure_class": self.failure_class,
            "downloaded": self.downloaded,
        }


class AcquisitionError(SystemExit):
    """Fatal acquisition with a structured result retained for callers."""

    def __init__(self, result: AcquisitionResult):
        self.result = result
        super().__init__(
            f"acquisition failed: {result.failure_class or FailureClass.UNKNOWN.value}"
        )


def validate_cookie_browser(value: str | None) -> str | None:
    """Validate the safe `browser[:profile]` subset accepted by yt-dlp."""
    if value is None:
        return None
    if any(char in value for char in ("/", "\\", "\n", "\r", "\0")):
        raise ValueError("WATCH_COOKIES_BROWSER contains an unsafe profile")
    browser, separator, profile = value.partition(":")
    browser = browser.lower()
    if browser not in COOKIE_BROWSERS:
        raise ValueError("WATCH_COOKIES_BROWSER names an unsupported browser")
    if separator and (not profile or not PROFILE_RE.fullmatch(profile)):
        raise ValueError("WATCH_COOKIES_BROWSER contains an invalid profile")
    return browser + (f":{profile}" if separator else "")


def validate_languages(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ("en",)  # preserve the inherited ordinary-path default
    raw = tuple(part.strip() for part in value.split(","))
    if not raw or any(not part for part in raw):
        raise ValueError("WATCH_LANGUAGE must be auto or an ordered language list")
    if raw == ("auto",):
        return raw
    if "auto" in raw or any(not LANGUAGE_RE.fullmatch(part) for part in raw):
        raise ValueError("WATCH_LANGUAGE must contain BCP-47-like language tags")
    return tuple(dict.fromkeys(part.lower() for part in raw))


def acquisition_config(file_values: dict[str, str]) -> dict[str, object]:
    """Resolve and validate acquisition configuration before network work."""
    def configured(name: str) -> str | None:
        value = os.environ.get(name)
        if value is None:
            value = file_values.get(name)
        value = value.strip() if value else ""
        return value or None

    cookie_spec = validate_cookie_browser(configured("WATCH_COOKIES_BROWSER"))
    languages = validate_languages(configured("WATCH_LANGUAGE"))
    clients_value = configured("WATCH_YOUTUBE_CLIENTS") or "tv,mweb"
    clients = tuple(part.strip() for part in clients_value.split(",") if part.strip())
    safe = lambda value: bool(value) and len(value) <= 32 and all(
        char.isalnum() or char in "_-" for char in value
    )
    if not clients or len(clients) > 3 or any(not safe(part) for part in clients):
        raise ValueError("WATCH_YOUTUBE_CLIENTS must contain one to three safe client names")
    return {"cookie_spec": cookie_spec, "languages": languages, "player_clients": clients}


def source_identity(source: str) -> str:
    """Hash a canonical URL without query/fragment, never retaining credentials."""
    parts = urlsplit(source)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    canonical = urlunsplit((parts.scheme.lower(), host + port, parts.path, "", ""))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def public_source_url(source: str) -> str:
    """Return source URL provenance without credentials, query, or fragment."""
    parts = urlsplit(source)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme.lower(), host + port, parts.path, "", ""))


def local_source_identity(path: Path) -> str:
    """Content identity for a local source without retaining its absolute path."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_youtube_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def classify_failure(stderr: str, exit_code: int) -> FailureClass | None:
    text = stderr.lower()
    patterns: tuple[tuple[FailureClass, tuple[str, ...]], ...] = (
        (FailureClass.LOGIN_REQUIRED, ("sign in to confirm", "login required", "authentication required")),
        (FailureClass.REGION_LOCKED, ("not available in your country", "geo-restricted", "region")),
        (FailureClass.PRIVATE_OR_DELETED, ("private video", "video unavailable", "has been removed", "deleted")),
        (FailureClass.UNSUPPORTED_EXTRACTOR, ("unsupported url", "no suitable extractor")),
        (FailureClass.SABR_CLIENT, ("sabr", "streaming data is missing", "player response")),
        (FailureClass.HTTP_429, ("http error 429", "too many requests", "status code 429")),
        (FailureClass.HTTP_403, ("http error 403", "forbidden", "status code 403")),
        (FailureClass.NETWORK_TIMEOUT, ("timed out", "timeout", "connection reset", "temporary failure")),
        (FailureClass.FORMAT_UNAVAILABLE, ("requested format is not available", "no video formats found")),
    )
    for failure, needles in patterns:
        if any(needle in text for needle in needles):
            return failure
    return FailureClass.UNKNOWN if exit_code else None


_AUTH_RE = re.compile(r"(?i)(authorization|cookie|set-cookie)(\s*[:=]\s*)\S+")
_URL_QUERY_RE = re.compile(r"https?://[^\s]+")


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    redacted = _AUTH_RE.sub(r"\1\2<redacted>", redacted)

    def clean_url(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            parts = urlsplit(value.rstrip(".,);]"))
            clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            return clean + ("<redacted-query>" if parts.query or parts.fragment else "")
        except ValueError:
            return "<redacted-url>"

    return _URL_QUERY_RE.sub(clean_url, redacted)


def _compact_detail(stderr: str, secrets: tuple[str, ...]) -> str | None:
    cleaned = redact_text(stderr, secrets).strip()
    if not cleaned:
        return None
    line = cleaned.splitlines()[-1]
    return line[:400]


def _caption_patterns(languages: tuple[str, ...]) -> str:
    if languages == ("auto",):
        return "en.*,en"
    ordered: list[str] = []
    for language in languages:
        for candidate in ((f"{language}.*", language.split("-", 1)[0])
                          if "-" in language else (f"{language}.*",)):
            if candidate not in ordered:
                ordered.append(candidate)
    return ",".join(ordered)


def build_yt_dlp_command(
    url: str,
    output_template: str,
    *,
    audio_only: bool,
    captions_only: bool,
    languages: tuple[str, ...],
    cookie_spec: str | None,
    player_client: str | None = None,
    final_format_fallback: bool = False,
    json3_captions: bool = False,
) -> list[str]:
    normal = "ba/bestaudio" if audio_only else "bv*[height<=720]+ba/b[height<=720]/bv+ba/b"
    if final_format_fallback and not audio_only:
        normal = f"{normal}/18"
    cmd = ["yt-dlp"]
    if captions_only:
        cmd.append("--skip-download")
    else:
        cmd += ["-N", "8", "-f", normal, "--merge-output-format", "mp4"]
    cmd += [
        "--write-info-json", "--write-subs", "--write-auto-subs",
        "--sub-langs", _caption_patterns(languages),
        "--sub-format", "json3" if json3_captions else "vtt",
        "--convert-subs", "vtt", "--no-playlist", "--ignore-errors",
    ]
    if player_client:
        cmd += ["--extractor-args", f"youtube:player_client={player_client}"]
    if cookie_spec:
        cmd += ["--cookies-from-browser", cookie_spec]
    cmd += ["-o", output_template, "--", url]
    return cmd


def acquire_url(
    url: str,
    out_dir: Path,
    *,
    audio_only: bool = False,
    captions_only: bool = False,
    languages: tuple[str, ...] = ("en",),
    cookie_spec: str | None = None,
    player_clients: tuple[str, ...] = ("tv", "mweb"),
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    pick_media: Callable[[Path], Path | None],
    pick_subtitles: Callable[[Path, tuple[str, ...]], list[Path]],
    read_metadata: Callable[[Path, str], dict],
) -> AcquisitionResult:
    """Acquire a URL through a bounded default-first recovery ladder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "video.%(ext)s")
    attempts: list[AcquisitionAttempt] = []
    warnings: list[str] = []
    last_failure: FailureClass | None = None
    secrets = (url, cookie_spec or "")

    strategies: list[tuple[str, str | None, bool]] = [("default", None, False)]
    if is_youtube_url(url):
        strategies += [(f"youtube-client:{client}", client, False) for client in player_clients]
        if not audio_only and not captions_only:
            strategies.append(("youtube-format-final:18", None, True))

    selected: str | None = None
    selected_stderr = ""
    for index, (strategy, client, final_format) in enumerate(strategies):
        if index and last_failure not in RETRYABLE_FAILURES:
            break
        cmd = build_yt_dlp_command(
            url, template, audio_only=audio_only, captions_only=captions_only,
            languages=languages, cookie_spec=cookie_spec, player_client=client,
            final_format_fallback=final_format,
        )
        completed = runner(cmd, capture_output=True, text=True)
        stderr = (completed.stderr or "") + (completed.stdout or "")
        media = None if captions_only else pick_media(out_dir)
        subtitles = pick_subtitles(out_dir, languages)
        success = bool(subtitles) if captions_only else media is not None
        failure = None if success else classify_failure(stderr, completed.returncode)
        attempts.append(AcquisitionAttempt(
            strategy=strategy,
            outcome="success" if success else "failed",
            failure_class=failure.value if failure else None,
            exit_code=completed.returncode,
            detail=None if success else _compact_detail(stderr, secrets),
        ))
        if success:
            selected = strategy
            selected_stderr = stderr
            break
        last_failure = failure or FailureClass.UNKNOWN

    media = None if captions_only else pick_media(out_dir)
    subtitles = pick_subtitles(out_dir, languages)

    if captions_only and not subtitles and any(
        attempt.failure_class == FailureClass.HTTP_429.value for attempt in attempts
    ):
        cmd = build_yt_dlp_command(
            url, template, audio_only=audio_only, captions_only=True,
            languages=languages, cookie_spec=cookie_spec, json3_captions=True,
        )
        completed = runner(cmd, capture_output=True, text=True)
        stderr = (completed.stderr or "") + (completed.stdout or "")
        subtitles = pick_subtitles(out_dir, languages)
        failure = None if subtitles else classify_failure(stderr, completed.returncode)
        attempts.append(AcquisitionAttempt(
            strategy="captions-json3-after-429",
            outcome="success" if subtitles else "failed",
            failure_class=failure.value if failure else None,
            exit_code=completed.returncode,
            detail=None if subtitles else _compact_detail(stderr, secrets),
        ))
        if subtitles:
            selected = "captions-json3-after-429"
            warnings.append("native captions recovered through JSON3 fallback")

    # Caption 429s can succeed at media acquisition while leaving no VTT.  Retry
    # captions only as JSON3, avoiding a second media download.
    caption_failure = classify_failure(selected_stderr, 0)
    if selected and not subtitles and caption_failure == FailureClass.HTTP_429:
        cmd = build_yt_dlp_command(
            url, template, audio_only=audio_only, captions_only=True,
            languages=languages, cookie_spec=cookie_spec, json3_captions=True,
        )
        completed = runner(cmd, capture_output=True, text=True)
        stderr = (completed.stderr or "") + (completed.stdout or "")
        subtitles = pick_subtitles(out_dir, languages)
        failure = None if subtitles else classify_failure(stderr, completed.returncode)
        attempts.append(AcquisitionAttempt(
            strategy="captions-json3-after-429",
            outcome="success" if subtitles else "failed",
            failure_class=failure.value if failure else None,
            exit_code=completed.returncode,
            detail=None if subtitles else _compact_detail(stderr, secrets),
        ))
        if subtitles:
            warnings.append("native captions recovered through JSON3 fallback")

    metadata = read_metadata(out_dir / "video.info.json", url)
    metadata["url"] = public_source_url(str(metadata.get("url") or url))
    if selected:
        degraded = selected != "default" or len(attempts) > 1
        if degraded:
            warnings.append(f"acquisition recovered via {selected}")
        return AcquisitionResult(
            state="degraded" if degraded else "success",
            media_path=str(media) if media else None,
            subtitle_candidates=[str(path) for path in subtitles],
            selected_subtitle=str(subtitles[0]) if subtitles else None,
            metadata=metadata or {"url": public_source_url(url)},
            source_identity=source_identity(url),
            attempts=attempts,
            selected_strategy=selected,
            warnings=warnings,
            fallback_reason=attempts[0].failure_class if degraded else None,
            downloaded=not captions_only,
        )

    failure = last_failure or FailureClass.UNKNOWN
    return AcquisitionResult(
        state="unavailable" if captions_only else "fatal",
        media_path=None,
        subtitle_candidates=[str(path) for path in subtitles],
        selected_subtitle=str(subtitles[0]) if subtitles else None,
        metadata=metadata or {"url": public_source_url(url)},
        source_identity=source_identity(url),
        attempts=attempts,
        failure_class=failure.value,
        downloaded=False,
    )
