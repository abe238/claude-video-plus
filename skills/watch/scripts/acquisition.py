#!/usr/bin/env python3
"""Deep, stdlib-only video acquisition Interface.

The default yt-dlp invocation always runs first.  Only classified, retryable
failures enter the bounded YouTube recovery ladder; attempt records contain no
URLs, cookies, headers, signed query strings, or local browser-profile paths.
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
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
    MAX_FILESIZE_EXCEEDED = "max_filesize_exceeded"
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
        message = f"acquisition failed: {result.failure_class or FailureClass.UNKNOWN.value}"
        if result.failure_class == FailureClass.MAX_FILESIZE_EXCEEDED.value:
            message += (
                " -- the media exceeds WATCH_MAX_FILESIZE. Raise or unset the cap"
                " in ~/.config/watch/.env, or use --detail transcript (no media"
                " download) for this video."
            )
        elif result.failure_class in (
            FailureClass.HTTP_403.value,
            FailureClass.SABR_CLIENT.value,
            FailureClass.FORMAT_UNAVAILABLE.value,
        ):
            # A 403 / SABR / format-gone on media download (metadata usually still
            # works) is the classic signature of an outdated yt-dlp after the
            # SITE changed its player/format. Keep the text source-neutral —
            # AcquisitionError is raised for every site, not just YouTube.
            message += (
                " -- the site likely changed its player or formats; an outdated"
                " yt-dlp is the usual cause. Upgrade with `python -m pip install"
                " -U yt-dlp` (or `pip install -U yt-dlp`) and retry. Installing a"
                " JS runtime (deno) also helps with signature challenges."
            )
        super().__init__(message)


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


def validate_max_filesize(value: str | None) -> str | None:
    """Validate the yt-dlp --max-filesize subset we accept (e.g. 500M, 1.5G)."""
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?[KMGkmg]?", value):
        raise ValueError("WATCH_MAX_FILESIZE must look like 500M, 1.5G, or bytes")
    return value


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
    max_filesize = validate_max_filesize(configured("WATCH_MAX_FILESIZE"))
    languages = validate_languages(configured("WATCH_LANGUAGE"))
    # android_vr is token-free; tv/mweb now gate their https formats behind a
    # GVS PO Token (tv: DRM-flagged, mweb: 403) that yt-dlp cannot supply without
    # cookies. Verified live 2026-07-25 against a real video: tv -> DRM error,
    # mweb -> "No video formats found", android_vr -> succeeds.
    clients_value = configured("WATCH_YOUTUBE_CLIENTS") or "android_vr,tv,mweb"
    clients = tuple(part.strip() for part in clients_value.split(",") if part.strip())
    safe = lambda value: bool(value) and len(value) <= 32 and all(
        char.isalnum() or char in "_-" for char in value
    )
    if not clients or len(clients) > 3 or any(not safe(part) for part in clients):
        raise ValueError("WATCH_YOUTUBE_CLIENTS must contain one to three safe client names")
    # --ignore-config suppresses an ambient ~/.config/yt-dlp/config. It is
    # ON whenever the video cache could participate (WATCH_VIDEO_CACHE=1),
    # because the cache's cookie-exclusion trusts our own cookie_used fact and
    # an ambient config injecting --cookies would silently falsify it. With the
    # cache off there is no such fact to protect, so a user's own config
    # (proxies, auth for their private videos) is respected — that ambient
    # config is home-dir-local, not repo-plantable like the v1.2.4 cwd-.env.
    ignore_config = str(configured("WATCH_VIDEO_CACHE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return {"cookie_spec": cookie_spec, "languages": languages, "player_clients": clients,
            "max_filesize": max_filesize, "ignore_config": ignore_config}


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
        (FailureClass.MAX_FILESIZE_EXCEEDED, ("larger than max-filesize",)),
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
_POSIX_PATH_RE = re.compile(r"(?<!:)(?<!\w)/(?:[^\s'\"/]+/)+[^\s'\"]*")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\(?:[^\s'\"\\]+\\)+[^\s'\"]*")


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

    redacted = _URL_QUERY_RE.sub(clean_url, redacted)
    redacted = _WINDOWS_PATH_RE.sub("<redacted-path>", redacted)
    return _POSIX_PATH_RE.sub("<redacted-path>", redacted)


def _clear_attempt_artifacts(out_dir: Path) -> None:
    """Remove only generated MEDIA files so stale partial output cannot signal
    success. Caption files (.vtt/.srt) are deliberately preserved: a prior
    captions-only fetch may have written them into this same directory, and
    deleting them made the evidence-mode caption fallback point at a dead path
    exactly when the media attempt's subtitle re-fetch flaked (L6 review).
    Stale-caption risk is nil — same source, same content; a successful
    re-fetch overwrites them anyway."""
    for path in out_dir.glob("video*"):
        if path.suffix.lower() in {".vtt", ".srt"}:
            continue
        if path.is_file() or path.is_symlink():
            try:
                path.unlink()
            except OSError:
                pass


def _compact_detail(stderr: str, secrets: tuple[str, ...]) -> str | None:
    cleaned = redact_text(stderr, secrets).strip()
    if not cleaned:
        return None
    line = cleaned.splitlines()[-1]
    return line[:400]


def _caption_patterns(languages: tuple[str, ...]) -> str:
    """yt-dlp --sub-langs pattern list (upstream PRs #92 yapaybaba + #123
    Nicopatron, via the bugsmithd fork audit).

    `.*-orig` / `{lang}-orig` request the spoken-language ORIGINAL track —
    without it a non-English video silently yields only machine translations.
    The old `en.*` wildcard is gone for English: it matched ~30 auto-translated
    variants that were never selected and triggered HTTP 429 on the way down
    (the explicit en/en-US/en-GB set keeps the tracks that ever win selection).
    Selection ordering — manual before ASR before translation — stays in
    download._subtitle_candidates; this only controls what gets FETCHED.
    """
    if languages == ("auto",):
        return ".*-orig,en,en-US,en-GB"
    ordered: list[str] = []

    def _add(candidate: str) -> None:
        if candidate not in ordered:
            ordered.append(candidate)

    def _canon(tag: str) -> str:
        # validate_languages lowercases; yt-dlp track codes use BCP-47 casing
        # (en-US, zh-Hant-TW), so restore it per subtag: base lowercase,
        # four-letter script Title Case, two-letter region uppercase.
        parts = tag.split("-")
        out = [parts[0].lower()]
        for sub in parts[1:]:
            if len(sub) == 2:
                out.append(sub.upper())
            elif len(sub) == 4:
                out.append(sub.title())
            else:
                out.append(sub)
        return "-".join(out)

    for language in map(_canon, languages):
        base = language.split("-", 1)[0]
        if "-" in language:
            _add(f"{language}-orig")  # regional originals exist (en-US-orig)
        _add(f"{base}-orig")
        if base.lower() == "en":
            for candidate in ("en", "en-US", "en-GB"):
                _add(candidate)
            if "-" in language:
                _add(language)
        else:
            _add(f"{language}.*")
            if "-" in language:
                _add(base)
    return ",".join(ordered)


# The staleness signature: a media download that 403s / SABRs / loses its format
# after metadata already succeeded is almost always an outdated yt-dlp behind a
# site player change (verified live 2026-08: 2026.07.04 403s on all YouTube
# media, 2026.08.19 works). These are the classes the self-heal upgrade targets.
STALE_YTDLP_FAILURES = frozenset({
    FailureClass.HTTP_403.value,
    FailureClass.SABR_CLIENT.value,
    FailureClass.FORMAT_UNAVAILABLE.value,
})

# Self-heal state, lock-guarded and process-scoped. `_force_module` makes the
# rest of the run use the freshly-upgraded pip module over a stale system/brew
# binary; `_upgrade_attempted` latches so AT MOST ONE automatic install runs per
# process, whether it succeeds or fails (evidence mode and repeated library calls
# can otherwise reach the download path more than once).
_ytdlp_state_lock = threading.Lock()
_force_module = False
_upgrade_attempted = False

# A trusted working directory for the pip/module subprocesses: our own scripts
# dir, never the caller's CWD (which under the untrusted-repo threat model could
# hold a planted `pip/__main__.py` or `yt_dlp/`).
_SAFE_CWD = str(Path(__file__).resolve().parent)


def _hardened_python(*args: str) -> tuple[str, ...]:
    """`python` invocation hardened against module-resolution hijacking: ``-E``
    drops PYTHON* env (PYTHONPATH/PYTHONHOME) on every version; ``-P`` (3.11+)
    drops the unsafe ``sys.path[0]`` prepend so a planted module in the CWD or
    script dir cannot shadow ``pip``/``yt_dlp``. User site-packages stay on the
    path, so a ``pip install --user`` upgrade remains importable."""
    flags = ["-E"]
    if sys.version_info >= (3, 11):
        flags.append("-P")
    return (sys.executable, *flags, *args)


def _hardened_subprocess_env() -> dict:
    """os.environ minus the variables that could redirect pip/module resolution:
    PYTHON* (path/home) and every PIP_* (index URL, constraints, config file).
    Then pin ``PIP_CONFIG_FILE=os.devnull`` — pip's documented switch to disable
    ALL configuration files (global AND site AND user), which ``--isolated`` does
    not fully cover — so a global/site pip.conf cannot inject an extra-index-url,
    find-links, or a version constraint that changes what installs."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME") and not k.startswith("PIP_")}
    env["PIP_CONFIG_FILE"] = os.devnull
    return env


def ytdlp_autoupdate_enabled(env: dict | None = None) -> bool:
    """Whether the self-heal may upgrade yt-dlp (default ON; opt out with
    WATCH_YTDLP_AUTOUPDATE=0/false/no/off). Honors env-over-file: a real
    environment variable wins; otherwise the passed ``.env`` mapping is used."""
    raw = os.environ.get("WATCH_YTDLP_AUTOUPDATE")
    if raw is None and env is not None:
        raw = env.get("WATCH_YTDLP_AUTOUPDATE")
    return str(raw or "").strip().lower() not in {"0", "false", "no", "off"}


def upgrade_ytdlp(runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                  timeout: int = 180) -> bool:
    """Best-effort, at-most-once-per-process yt-dlp upgrade for the self-heal.

    Upgrades the pip ``--user`` copy — the one install path we can drive
    portably (brew/pipx we cannot). Hardened: FIXED argv (no untrusted input);
    ``pip --isolated`` + explicit official ``--index-url`` so PIP_* env/config
    cannot redirect the source or version; run under ``_hardened_python`` in a
    trusted CWD with a stripped env so no planted module hijacks resolution. Only
    after the upgraded module PROVES runnable (``-m yt_dlp --version``) does it
    force the module path. Returns False on any failure (offline, PEP 668, no
    pip, unrunnable) so the caller keeps the actionable manual message.
    """
    global _force_module, _upgrade_attempted
    # Hold the lock for the WHOLE upgrade so a concurrent caller BLOCKS until it
    # finishes and then observes the final _force_module, rather than latching on
    # a still-in-progress attempt and getting a premature False.
    with _ytdlp_state_lock:
        if _upgrade_attempted:
            return _force_module  # already tried this process — never reinstall
        _upgrade_attempted = True
        safe_env = _hardened_subprocess_env()
        install = _hardened_python(
            "-m", "pip", "install", "--isolated",
            "--index-url", "https://pypi.org/simple/",
            "--user", "--upgrade", "yt-dlp",
        )
        try:
            completed = runner(list(install), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=timeout, env=safe_env, cwd=_SAFE_CWD)
        except (OSError, subprocess.SubprocessError):
            return False
        if getattr(completed, "returncode", 1) != 0:
            return False
        # Verify the upgraded module actually runs before trusting it (a zero pip
        # exit does not guarantee an importable/runnable yt_dlp under --user).
        probe = list(_hardened_python("-m", "yt_dlp", "--version"))
        try:
            checked = runner(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             timeout=30, env=safe_env, cwd=_SAFE_CWD)
        except (OSError, subprocess.SubprocessError):
            return False
        if getattr(checked, "returncode", 1) != 0:
            return False
        _force_module = True
        return True


def ytdlp_cmd() -> tuple[str, ...]:
    """Working yt-dlp invocation. The ``_force_module`` check is UNCACHED so a
    mid-run self-heal upgrade takes effect immediately without racing an
    lru_cache repopulation; the (stable) executable/module probe below is
    cached."""
    with _ytdlp_state_lock:
        forced = _force_module
    if forced:
        return _hardened_python("-m", "yt_dlp")
    return _detect_ytdlp_cmd()


@functools.lru_cache(maxsize=1)
def _detect_ytdlp_cmd() -> tuple[str, ...]:
    """Probe a working yt-dlp once per process.

    Windows Smart App Control / WDAC blocks the unsigned yt-dlp.exe shim at
    *execution* time (OSError) while ``shutil.which`` still finds it, so
    presence on PATH is not proof of usability. Prefer the executable; fall
    back to ``python -m yt_dlp`` (hardened) when the exe is blocked or absent
    but the module is importable. Fails open to ``("yt-dlp",)`` so callers keep
    today's error paths when nothing is usable.
    """
    exe = shutil.which("yt-dlp")
    if exe is not None:
        try:
            subprocess.run(
                [exe, "--version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
            )
            return ("yt-dlp",)
        except (OSError, subprocess.CalledProcessError) as exc:
            # Either it cannot start (policy block) or it starts and fails its
            # own --version (broken/intercepted shim). Both mean "do not trust
            # this executable" — fall through and try the module, which may
            # work. Returning early here pinned every acquisition to a shim
            # already known to be broken.
            print(
                f"[watch] yt-dlp executable is present but not usable ({exc}); "
                "trying `python -m yt_dlp`.",
                file=sys.stderr,
            )
    module = _hardened_python("-m", "yt_dlp")
    try:
        subprocess.run(
            [*module, "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
            cwd=_SAFE_CWD,
        )
        return module
    except (OSError, subprocess.CalledProcessError):
        return ("yt-dlp",)


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
    max_filesize: str | None = None,
    ignore_config: bool = True,
) -> list[str]:
    # Format ladder (video): strict <=720 first, then <=?720 rungs that also keep
    # formats carrying NO resolution metadata (HLS / generic-extractor manifests),
    # then a BOUNDED worst-rendition tail (wv*+ba/w). The old unbounded `bv+ba/b`
    # tail would fetch a 4K upload whenever no <=720 rendition was tagged — slow,
    # bandwidth-heavy, and a needless WATCH_MAX_FILESIZE trip. (fork-watch:
    # androsland/moviola.)
    normal = (
        "ba/bestaudio" if audio_only
        else "bv*[height<=720]+ba/b[height<=720]"
             "/bv*[height<=?720]+ba/b[height<=?720]"
             "/wv*+ba/w"
    )
    if final_format_fallback and not audio_only:
        normal = f"{normal}/18"
    cmd = [*ytdlp_cmd()]
    if ignore_config:
        # Ambient ~/.config/yt-dlp config can add --cookies (falsifying the
        # cache's non-authenticated fact) or any flag this pipeline never
        # agreed to. Suppressed whenever the cache could participate; see
        # acquisition_config for the scope rationale.
        cmd.append("--ignore-config")
    # --no-exec is UNCONDITIONAL (v1.5.6, donlapidos): nothing legitimate in a
    # transcription pipeline needs yt-dlp --exec post-processing, so the
    # CLI-exec surface stays closed on every run, cache or not.
    cmd.append("--no-exec")
    if captions_only:
        cmd.append("--skip-download")
    else:
        cmd += ["-N", "8", "-f", normal, "--merge-output-format", "mp4"]
        if max_filesize:
            # media only: caption/metadata fetches are tiny and stay unguarded
            cmd += ["--max-filesize", max_filesize]
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
    max_filesize: str | None = None,
    player_clients: tuple[str, ...] = ("android_vr", "tv", "mweb"),
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    pick_media: Callable[[Path], Path | None],
    pick_subtitles: Callable[[Path, tuple[str, ...]], list[Path]],
    read_metadata: Callable[[Path, str], dict],
    ignore_config: bool = True,
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
        _clear_attempt_artifacts(out_dir)
        cmd = build_yt_dlp_command(
            url, template, audio_only=audio_only, captions_only=captions_only,
            languages=languages, cookie_spec=cookie_spec, max_filesize=max_filesize, player_client=client,
            final_format_fallback=final_format, ignore_config=ignore_config,
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
            languages=languages, cookie_spec=cookie_spec, max_filesize=max_filesize, json3_captions=True,
            ignore_config=ignore_config,
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
            languages=languages, cookie_spec=cookie_spec, max_filesize=max_filesize, json3_captions=True,
            ignore_config=ignore_config,
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

    # Prefer the most informative failure ACROSS attempts, not just the last: a
    # later retry with a forced client/format can fail with a noisier,
    # less-actionable error (UNKNOWN, FORMAT_UNAVAILABLE) that would otherwise
    # MASK a real HTTP_403 / auth / rate-limit cause the first attempt already
    # identified. Live-observed: a stale yt-dlp 403s on the default strategy,
    # then the forced-format retry reports UNKNOWN, so users saw "failed:
    # unknown" for what is really an upgrade-yt-dlp situation.
    informative = next(
        (attempt.failure_class for attempt in attempts
         if attempt.failure_class and attempt.failure_class != FailureClass.UNKNOWN.value),
        None,
    )
    failure_value = informative or (last_failure or FailureClass.UNKNOWN).value
    return AcquisitionResult(
        state="unavailable" if captions_only else "fatal",
        media_path=None,
        subtitle_candidates=[str(path) for path in subtitles],
        selected_subtitle=str(subtitles[0]) if subtitles else None,
        metadata=metadata or {"url": public_source_url(url)},
        source_identity=source_identity(url),
        attempts=attempts,
        failure_class=failure_value,
        downloaded=False,
    )
