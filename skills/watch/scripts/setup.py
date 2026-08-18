#!/usr/bin/env python3
"""Setup / preflight for /watch.

Modes:
  setup.py --check      Silent preflight. Exit 0 if ready, 2/3/4 on failure.
  setup.py --json       Machine-readable status for Claude to parse.
  setup.py              Installer. Auto-installs deps, scaffolds .env, marks SETUP_COMPLETE.

Design:
- Silent on success: --check exits 0 with no output when everything's ready so
  that /watch doesn't spam "setup is complete" on every turn.
- Idempotent: re-running the installer is safe — it never clobbers existing
  keys and only appends missing ones.
- SETUP_COMPLETE=true in ~/.config/watch/.env tells us the user has been
  through a successful installer run at least once.
- Never sudo. On macOS, auto-install via brew. Elsewhere, print exact commands.
- Never write an API key to disk automatically — only scaffold placeholders.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.parse
from pathlib import Path

# Legacy Windows consoles use a locale codepage (cp1252, cp949, cp936, ...) that
# cannot encode the em dashes and arrows this script prints, so a plain print()
# raises UnicodeEncodeError and kills the run. Force UTF-8 on the way out;
# non-TextIO streams (pytest capture, pipes) are left alone.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-TextIO stream
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from config import DEFAULT_STT_URL, get_config  # noqa: E402


REQUIRED_BINARIES = ["ffmpeg", "ffprobe", "yt-dlp"]
CONFIG_DIR = Path.home() / ".config" / "watch"
CONFIG_FILE = CONFIG_DIR / ".env"
ENV_TEMPLATE = """# /watch configuration
#
# Transcription is only needed when yt-dlp cannot get captions (or you point
# /watch at a local file with no subtitles). Adapters are tried in order:
#
#   1. local-http   local OpenAI-compatible STT server (default 127.0.0.1:8082)
#   2. yap          on-device Apple Speech, macOS only
#                   (brew install finnvoor/tools/yap)
#   3. groq/openai  cloud Whisper — audio leaves your machine
#
# Local Adapters are detected, never installed. Leave everything blank and
# /watch still works: caption-less video just comes back frames-only.
#
# A cloud key on its own does NOTHING. The cloud Adapters refuse unless you
# also pass --allow-remote-transcription (or set WATCH_STT_ALLOW_REMOTE=true
# below). That is deliberate: audio is never uploaded without explicit consent.
#
# Get a Groq key:  https://console.groq.com/keys
# Get an OpenAI key:  https://platform.openai.com/api-keys

GROQ_API_KEY=
OPENAI_API_KEY=

# Default watch behavior (the /watch first-run wizard sets this for you).
# Allowed values: transcript | efficient | balanced | token-burner
# Keep the value on its own line with no trailing comment.
# WATCH_DETAIL=balanced

# Frame engine (default v2: color-aware dedup + coverage floor). Set v1 to
# restore the previous engine.
# WATCH_FRAME_ENGINE=v2

# Optional local-first transcription. Native captions and same-name .vtt/.srt
# sidecars always run before these Adapters. Nothing is installed automatically.
# WATCH_STT_ORDER=local-http,yap,groq,openai
# WATCH_STT_URL=http://127.0.0.1:8082
# WATCH_STT_MODEL=Systran/faster-whisper-medium
# WATCH_LANGUAGE=auto
# WATCH_STT_ALLOW_REMOTE=false

# Acquisition recovery remains default-first. Cookies are explicit and optional.
# WATCH_COOKIES_BROWSER=chrome
# WATCH_YOUTUBE_CLIENTS=android_vr,tv,mweb
"""


def _which(name: str) -> str | None:
    return shutil.which(name)


def _check_binaries() -> list[str]:
    """Binaries with no working runtime substitute.

    v1.3.6 added two fallbacks for machines where an App Control policy blocks
    an unsigned executable: ffprobe -> parse the `ffmpeg -i` banner, and the
    yt-dlp shim -> `python -m yt_dlp`. Reporting those as missing here would
    fail Step 0 and stop the user before the fallback could ever run, so a
    binary counts as present when its substitute is usable.
    """
    missing = []
    for binary in REQUIRED_BINARIES:
        if _which(binary):
            continue
        if binary == "ffprobe" and _which("ffmpeg"):
            continue  # frames.get_metadata / whisper.audio_duration parse the banner
        if binary == "yt-dlp" and _yt_dlp_module_available():
            continue  # acquisition.ytdlp_cmd() selects `python -m yt_dlp`
        missing.append(binary)
    return missing


def _yt_dlp_module_available() -> bool:
    try:
        return subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# yt-dlp version strings ARE release dates (YYYY.MM.DD), so staleness is a
# pure offline computation — no network, no update check. A stale yt-dlp is
# the #1 real-world breakage (YouTube extractor churn → HTTP 400/403 on
# videos that play fine in a browser). Warn-only: never blocks a run.
# Prior art: fire17/claude-video (feat/ytdlp-staleness-guard), adapted to our
# module-fallback resolution. Env knob doubles as the deterministic test seam.
def _stale_threshold_days() -> int:
    """WATCH_YTDLP_STALE_DAYS, parsed defensively: a malformed or negative
    value must degrade to the default, never crash preflight."""
    raw = os.environ.get("WATCH_YTDLP_STALE_DAYS", "")
    try:
        value = int(raw)
        return value if value >= 0 else 120
    except ValueError:
        return 120


YTDLP_STALE_DAYS = _stale_threshold_days()


def _youtube_js_runtime() -> str | None:
    """Which supported JS runtime yt-dlp can use for YouTube's EJS challenges.

    VERIFIED 2026-08-18 both ways: yt-dlp 2026.06.09 enables only deno by
    default (node/quickjs/bun need --js-runtimes) and warns that runtime-less
    YouTube extraction "has been deprecated, and some formats may be missing"
    — but it does NOT fail today (same format list either way in our probe).
    So this is surfaced in --json and as an install hint, never a --check
    warning: it is futureproofing, not current breakage. Prior art:
    jryyangjy/claude-video (feat/youtube-deps-preflight-67), severity
    corrected against measurement.
    """
    return "deno" if _which("deno") else None


def _js_runtime_installed_not_enabled() -> str | None:
    """A runtime yt-dlp could use but does not enable by default (needs
    --js-runtimes). Reported separately so a node-only host is never counted
    as covered — yt-dlp will not touch node without explicit wiring."""
    if _which("deno"):
        return None
    for runtime in ("node", "bun", "quickjs"):
        if _which(runtime):
            return runtime
    return None


def _ytdlp_age_days() -> int | None:
    """Days since the installed yt-dlp's release date, or None if unknowable."""
    for cmd in (["yt-dlp", "--version"],
                [sys.executable, "-m", "yt_dlp", "--version"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if out.returncode != 0:
                continue
            m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", out.stdout)
            if not m:
                continue
            released = datetime.date(int(m[1]), int(m[2]), int(m[3]))
            return (datetime.date.today() - released).days
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            continue
    return None


_PERM_WARNED: set[str] = set()


# Principals expected to reach a per-user secrets file on Windows.
# Well-known SIDs, so this stays correct on non-English installs.
_WIN_OK_SIDS = {
    "S-1-5-18",      # NT AUTHORITY\SYSTEM
    "S-1-5-32-544",  # BUILTIN\Administrators
}


def _windows_extra_readers(path: Path) -> list[str] | None:
    """SIDs beyond the current user/SYSTEM/Administrators allowed on `path`.

    POSIX mode bits are meaningless on Windows: os.stat() reports 0o666 for
    any writable file and os.chmod() only toggles the read-only flag, so the
    Unix `mode & 0o044` test is a guaranteed false positive there. Read the
    real NTFS ACL via PowerShell instead. Returns None when the ACL cannot be
    determined (no PowerShell, timeout, error) — callers must treat that as
    "unknown", not "safe".
    """
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps is None:
        return None
    literal = str(path).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        "$me=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        f"foreach ($a in (Get-Acl -LiteralPath '{literal}').Access) {{"
        "  if ($a.AccessControlType -ne 'Allow') { continue }"
        "  try { $sid=$a.IdentityReference.Translate("
        "[Security.Principal.SecurityIdentifier]).Value }"
        "  catch { $sid=$a.IdentityReference.Value }"
        "  if ($sid -ne $me) { Write-Output $sid }"
        "}"
    )
    try:
        result = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    seen: list[str] = []
    for line in result.stdout.splitlines():
        sid = line.strip()
        if sid and sid not in _WIN_OK_SIDS and sid not in seen:
            seen.append(sid)
    return seen


def _check_file_permissions(path: Path) -> None:
    """Warn to stderr (once per path per process) if a secrets file is
    readable by others.

    Unix: group/other mode bits. Windows: the real NTFS ACL (mode bits are
    meaningless there — see _windows_extra_readers), warning with an icacls
    remediation instead of chmod.
    """
    key = str(path)
    if key in _PERM_WARNED:
        return
    if platform.system() == "Windows":
        extra = _windows_extra_readers(path)
        if extra:
            _PERM_WARNED.add(key)
            sys.stderr.write(
                f"[watch] WARNING: {path} is accessible to {', '.join(extra)}. "
                f'Fix: icacls "{path}" /inheritance:r '
                f'/grant:r "%USERNAME%:F" "SYSTEM:F" "Administrators:F"\n'
            )
            sys.stderr.flush()
        return
    try:
        mode = path.stat().st_mode
        if mode & 0o044:
            _PERM_WARNED.add(key)
            sys.stderr.write(
                f"[watch] WARNING: {path} is readable by other users. "
                f"Run: chmod 600 {path}\n"
            )
            sys.stderr.flush()
    except OSError:
        pass


def _read_env_key(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    if not CONFIG_FILE.exists():
        return None
    _check_file_permissions(CONFIG_FILE)
    try:
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            if key.strip() != name:
                continue
            raw = raw.strip()
            if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                raw = raw[1:-1]
            return raw or None
    except OSError:
        return None
    return None


def _have_api_key() -> tuple[bool, str | None]:
    if _read_env_key("GROQ_API_KEY"):
        return True, "groq"
    if _read_env_key("OPENAI_API_KEY"):
        return True, "openai"
    return False, None


def _loopback_listening(url: str) -> bool:
    """True if something is accepting connections at `url`'s host:port."""
    try:
        parts = urllib.parse.urlsplit(url if "://" in url else f"http://{url}")
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not host:
            return False
        # ponytail: a TCP connect, not an HTTP probe. The runtime Adapter does
        # the real handshake and fails open; setup only needs "is anything
        # there". Localhost refuses instantly, so --check stays sub-100ms.
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except (OSError, ValueError):
        return False


def _local_stt_backends() -> list[str]:
    """Local transcription Adapters available right now, in runtime order.

    Mirrors config.DEFAULT_STT_ORDER's local half (local-http, yap, whisper-cli).
    Detection only — /watch never installs any of them. A local backend fully
    satisfies transcription, which is why its presence makes setup `ready` with
    no cloud key: the cloud Adapters refuse without explicit remote
    authorization anyway, so a key alone would not transcribe anything.
    """
    found: list[str] = []
    url = _read_env_key("WATCH_STT_URL") or DEFAULT_STT_URL
    if _loopback_listening(url):
        found.append("local-http")
    if platform.system() == "Darwin":
        yap = _read_env_key("WATCH_YAP_PATH") or "yap"
        if shutil.which(yap):
            found.append("yap")
    # The only local option on a bare Linux box.
    whisper_cli = _read_env_key("WATCH_WHISPER_CLI_PATH") or "whisper"
    if shutil.which(whisper_cli):
        found.append("whisper-cli")
    return found


def is_first_run() -> bool:
    """True if the installer hasn't completed successfully yet."""
    return _read_env_key("SETUP_COMPLETE") != "true"


def _scaffold_env() -> bool:
    """Create ~/.config/watch/.env with placeholders if missing."""
    if CONFIG_FILE.exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass
    return True


def _write_setup_complete() -> None:
    """Idempotently append SETUP_COMPLETE=true to .env.

    Used only after a fully successful install (deps + key). Future sessions
    detect this marker to skip wizard-style UI and stay silent.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = ""
    if CONFIG_FILE.exists():
        existing = CONFIG_FILE.read_text(encoding="utf-8")
        for line in existing.splitlines():
            if line.strip().startswith("SETUP_COMPLETE="):
                return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        CONFIG_FILE.write_text(existing + "SETUP_COMPLETE=true\n", encoding="utf-8")
    else:
        CONFIG_FILE.write_text(ENV_TEMPLATE + "\nSETUP_COMPLETE=true\n", encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def _brew_pkg(missing: list[str]) -> list[str]:
    pkgs: list[str] = []
    for bin_name in missing:
        if bin_name in ("ffmpeg", "ffprobe"):
            if "ffmpeg" not in pkgs:
                pkgs.append("ffmpeg")
        elif bin_name == "yt-dlp":
            if "yt-dlp" not in pkgs:
                pkgs.append("yt-dlp")
        else:
            pkgs.append(bin_name)
    return pkgs


def _install_macos(missing: list[str]) -> tuple[bool, str]:
    if _which("brew") is None:
        return False, (
            "Homebrew is not installed. Install it from https://brew.sh, then re-run setup. "
            "Or install manually: `brew install " + " ".join(_brew_pkg(missing)) + "`"
        )
    pkgs = _brew_pkg(missing)
    if not pkgs:
        return True, "nothing to install"
    cmd = ["brew", "install", *pkgs]
    print(f"[setup] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return False, f"brew install failed with exit code {result.returncode}"
    return True, f"installed via brew: {', '.join(pkgs)}"


def _install_hint_linux(missing: list[str]) -> str:
    pkgs = _brew_pkg(missing)
    hints = []
    if "ffmpeg" in pkgs:
        hints.append("apt: `sudo apt install ffmpeg` or dnf: `sudo dnf install ffmpeg`")
    if "yt-dlp" in pkgs:
        hints.append("`pipx install yt-dlp` (recommended) or `pip install --user yt-dlp`")
    return "\n  ".join(hints) if hints else "nothing to install"


def _install_hint_windows(missing: list[str]) -> str:
    pkgs = _brew_pkg(missing)
    hints = []
    if "ffmpeg" in pkgs:
        hints.append("winget: `winget install Gyan.FFmpeg`")
    if "yt-dlp" in pkgs:
        hints.append("winget: `winget install yt-dlp.yt-dlp` or pip: `pip install --user yt-dlp`")
    return "\n  ".join(hints) if hints else "nothing to install"


def _status() -> dict:
    """Structured preflight snapshot.

    `status` describes the *ideal* state (a Whisper key is encouraged), so a
    keyless install still reports `needs_key` on the very first run — that's
    the agent's cue to encourage adding one.

    `can_proceed` is the operational gate: /watch can run as long as the
    binaries are present AND the user has either set a key or already finished
    setup (consciously opting out of Whisper). A keyless user who completed
    setup is NOT nagged on every call.
    """
    missing = _check_binaries()
    has_key, backend = _have_api_key()
    local_stt = _local_stt_backends()
    setup_complete = not is_first_run()

    # A reachable local Adapter transcribes on its own, so it satisfies the
    # transcription requirement exactly as a cloud key does (better, in fact:
    # cloud refuses without WATCH_STT_ALLOW_REMOTE / --allow-remote-transcription).
    has_transcription = has_key or bool(local_stt)

    if not missing and has_transcription:
        status = "ready"
    elif missing and not has_transcription:
        status = "needs_install_and_key"
    elif missing:
        status = "needs_install"
    else:
        status = "needs_key"

    can_proceed = (not missing) and (has_transcription or setup_complete)

    cfg = get_config()
    ytdlp_age = _ytdlp_age_days() if "yt-dlp" not in missing else None
    return {
        "status": status,
        "can_proceed": can_proceed,
        "first_run": not setup_complete,
        "setup_complete": setup_complete,
        "missing_binaries": missing,
        "whisper_backend": backend,
        "has_api_key": has_key,
        "local_stt": local_stt,
        "ytdlp_age_days": ytdlp_age,
        "ytdlp_stale": bool(ytdlp_age is not None and ytdlp_age > YTDLP_STALE_DAYS),
        "youtube_js_runtime": _youtube_js_runtime(),
        "youtube_js_runtime_other": _js_runtime_installed_not_enabled(),
        "config_file": str(CONFIG_FILE),
        "watch_detail": cfg["detail"],
        "platform": platform.system(),
    }


def cmd_check() -> int:
    """Silent-on-success preflight.

    Exit 0 with no output when /watch can run. A keyless user who already
    finished setup (SETUP_COMPLETE=true) counts as ready — Whisper is
    encouraged, not required — so they are never nagged on follow-up calls.

    On a state that blocks /watch, print one actionable line to stderr:
      2 → binaries missing
      3 → genuine first run with no API key (encourage one)
      4 → both missing
      5 → runnable, but the first-run wizard never completed

    Exit 5 exists because `can_proceed` can be true while SETUP_COMPLETE is
    false (binaries present and a backend already configured by hand). Before
    v1.4.1 that returned 0, and since SKILL.md's slimmed Step 0 only calls
    --check, the first-run detail preference was never asked and
    SETUP_COMPLETE was never written — silently, on every such install.
    """
    s = _status()
    if s["can_proceed"] and s["setup_complete"]:
        if s.get("ytdlp_stale"):
            sys.stderr.write(
                f"[watch] yt-dlp is {s['ytdlp_age_days']} days old — YouTube "
                "breaks fast on stale extractors (HTTP 400/403). Update it "
                "(brew upgrade yt-dlp / pipx upgrade yt-dlp / pip install -U yt-dlp).\n"
            )
        return 0
    if s["can_proceed"]:
        sys.stderr.write(
            "[watch] ready to run, but first-run setup never completed "
            "(SETUP_COMPLETE is unset). Ask the one-time detail preference, "
            "then write SETUP_COMPLETE=true.\n"
        )
        sys.stderr.flush()
        return 5

    parts = []
    if s["missing_binaries"]:
        parts.append(f"missing binaries: {', '.join(s['missing_binaries'])}")
    if not s["has_api_key"] and not s["local_stt"] and not s["setup_complete"]:
        parts.append("no transcription backend (install yap, run a local STT server, or set a cloud key)")
    installer = Path(__file__).resolve()
    sys.stderr.write(
        f"[watch] setup incomplete ({'; '.join(parts)}). "
        f"Run: python3 {installer}\n"
    )
    sys.stderr.flush()

    if s["missing_binaries"] and not s["has_api_key"]:
        return 4
    if s["missing_binaries"]:
        return 2
    return 3


def cmd_json() -> int:
    json.dump(_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_install() -> int:
    missing = _check_binaries()
    installed_deps = False
    if missing:
        system = platform.system()
        if system == "Darwin":
            ok, msg = _install_macos(missing)
            print(f"[setup] {msg}", file=sys.stderr)
            if not ok:
                return 2
            still_missing = _check_binaries()
            if still_missing:
                print(f"[setup] still missing after install: {', '.join(still_missing)}", file=sys.stderr)
                return 2
            installed_deps = True
        elif system == "Linux":
            print("[setup] dependencies missing on Linux — please install:", file=sys.stderr)
            print("  " + _install_hint_linux(missing), file=sys.stderr)
            return 2
        elif system == "Windows":
            print("[setup] dependencies missing on Windows — please install:", file=sys.stderr)
            print("  " + _install_hint_windows(missing), file=sys.stderr)
            return 2
        else:
            print(f"[setup] unsupported platform ({system}) for auto-install. Install manually:", file=sys.stderr)
            print(f"  missing: {', '.join(missing)}", file=sys.stderr)
            return 2

    created = _scaffold_env()
    if created:
        print(f"[setup] created config: {CONFIG_FILE}")
    else:
        print(f"[setup] config exists: {CONFIG_FILE}")

    if _youtube_js_runtime() is None:
        other = _js_runtime_installed_not_enabled()
        extra = (f" You have {other}, but yt-dlp only enables deno by default "
                 f"(others need --js-runtimes {other})." if other else "")
        print("[setup] optional: yt-dlp has deprecated YouTube extraction "
              "without a JavaScript runtime (some formats may go missing as "
              "YouTube rolls out EJS challenges). Install deno to stay ahead: "
              "brew install deno / https://deno.land" + extra)

    has_key, backend = _have_api_key()
    if has_key:
        _write_setup_complete()
        print(f"[setup] ready. whisper backend: {backend}")
        if installed_deps:
            print("[setup] installed dependencies; /watch is fully set up.")
        return 0

    print("")
    print("[setup] optional: add a transcription backend for caption-less video.")
    print("")
    print("  Native captions and .vtt/.srt sidecars always run first, so most")
    print("  YouTube links need nothing here. A backend only matters for local")
    print("  files and videos with no captions. /watch tries them in this order:")
    print("")
    print("    1. local-http   a local OpenAI-compatible STT server, default 127.0.0.1:8082")
    if platform.system() == "Darwin":
        print("    2. yap          on-device Apple Speech (brew install finnvoor/tools/yap)")
    else:
        print("       (yap is macOS-only and is skipped on this platform)")
    print("    3. whisper-cli  a real speech model on this machine, any platform:")
    print("                    pip install openai-whisper")
    print("    4. groq / openai  cloud Whisper, and ONLY with explicit authorization:")
    print("       a key alone does nothing without --allow-remote-transcription")
    print("       (or WATCH_STT_ALLOW_REMOTE=true). Audio leaves your machine.")
    print("")
    print("  Local backends are detected, never installed. Nothing is uploaded by default.")
    print(f"  Cloud keys, if you want them, go in {CONFIG_FILE} (GROQ_API_KEY / OPENAI_API_KEY).")
    print("")
    print("  With no backend at all, /watch still works: caption-less video comes back frames-only.")
    return 3


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--check":
            return cmd_check()
        if arg == "--json":
            return cmd_json()
    return cmd_install()


if __name__ == "__main__":
    raise SystemExit(main())
