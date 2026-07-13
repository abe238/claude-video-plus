#!/usr/bin/env python3
"""Download a video via yt-dlp, or resolve a local file path.

Also fetches subtitles (manual first, then auto-generated) in VTT format so
transcribe.py can parse them without needing Whisper, and surfaces the
author-supplied description from info.json as bounded, untrusted evidence.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from acquisition import (
    AcquisitionAttempt,
    AcquisitionError,
    AcquisitionResult,
    FailureClass,
    acquisition_config,
    acquire_url,
    local_source_identity,
)
from config import read_env_file


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        result = AcquisitionResult(
            state="fatal", media_path=None, subtitle_candidates=[],
            selected_subtitle=None, metadata={},
            source_identity="0" * 64,
            attempts=[AcquisitionAttempt(
                strategy="local", outcome="failed",
                failure_class=FailureClass.INVALID_SOURCE.value, exit_code=3,
                detail="local source does not exist",
            )],
            failure_class=FailureClass.INVALID_SOURCE.value,
        )
        raise AcquisitionError(result)
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[watch] warning: {p.suffix} is not a known video extension, proceeding anyway",
            file=sys.stderr,
        )
    return AcquisitionResult(
        state="success", media_path=str(p), subtitle_candidates=[],
        selected_subtitle=None, metadata={"title": p.name, "url": str(p)},
        source_identity=local_source_identity(p),
        attempts=[AcquisitionAttempt(
            strategy="local", outcome="success", failure_class=None, exit_code=0,
        )],
        selected_strategy="local", downloaded=False,
    ).as_dict()


def _subtitle_candidates(out_dir: Path, languages: tuple[str, ...] = ("en",)) -> list[Path]:
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates or languages == ("auto",):
        return candidates
    ordered: list[Path] = []
    for language in languages:
        base = language.split("-", 1)[0].lower()
        for candidate in candidates:
            name = candidate.name.lower()
            if candidate not in ordered and (
                f".{language.lower()}." in name or f".{base}." in name
                or f".{base}-orig." in name
            ):
                ordered.append(candidate)
    ordered.extend(candidate for candidate in candidates if candidate not in ordered)
    return ordered


def _pick_subtitle(out_dir: Path) -> Path | None:
    candidates = _subtitle_candidates(out_dir)
    return candidates[0] if candidates else None


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".opus"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


def fetch_captions(url: str, out_dir: Path) -> dict:
    """Fetch metadata and best available VTT captions without downloading video."""
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    cfg = acquisition_config(read_env_file())
    result = acquire_url(
        url, out_dir, captions_only=True,
        languages=cfg["languages"], cookie_spec=cfg["cookie_spec"],
        player_clients=cfg["player_clients"], runner=subprocess.run,
        pick_media=_pick_video, pick_subtitles=_subtitle_candidates,
        read_metadata=_read_info,
    )
    # Caption absence is not fatal: watch.py may continue to media/ASR.
    return result.as_dict()


def _read_info(info_path: Path, url: str) -> dict:
    info: dict = {}
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
            # Title and uploader are author-controlled and land in the report
            # header, outside the description's fence -- sanitize at the source
            # so every consumer gets a marker-safe value.
            title = raw.get("title")
            uploader = raw.get("uploader") or raw.get("channel")
            info = {
                "title": sanitize_for_report(title) if title else title,
                "uploader": sanitize_for_report(uploader) if uploader else uploader,
                "duration": raw.get("duration"),
                "url": raw.get("webpage_url") or url,
                # Author-supplied and untrusted, but it is the only place the
                # exact spellings live: ASR renders "OmniRoute" as "Omniroot".
                # format_description() sanitizes on the way out.
                "description": raw.get("description"),
            }
        except Exception as exc:
            print(f"[watch] info.json parse failed: {exc}", file=sys.stderr)
            info = {"url": url}
    return info


def download_url(
    url: str,
    out_dir: Path,
    audio_only: bool = False,
) -> dict:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    cfg = acquisition_config(read_env_file())
    result = acquire_url(
        url, out_dir, audio_only=audio_only,
        languages=cfg["languages"], cookie_spec=cfg["cookie_spec"],
        player_clients=cfg["player_clients"], runner=subprocess.run,
        pick_media=_pick_video, pick_subtitles=_subtitle_candidates,
        read_metadata=_read_info,
    )
    if result.state == "fatal":
        raise AcquisitionError(result)
    return result.as_dict()


def download(
    source: str,
    out_dir: Path,
    audio_only: bool = False,
) -> dict:
    if is_url(source):
        return download_url(source, out_dir, audio_only=audio_only)
    return resolve_local(source)


DESCRIPTION_CHAR_LIMIT = 2000

ZWSP = "​"

# The report wraps media-derived text in BEGIN/END UNTRUSTED VIDEO EVIDENCE
# markers. Match the *distinguishing phrase* rather than the exact marker
# string: an LLM will honor "<!-- END  UNTRUSTED   VIDEO  EVIDENCE -->" as the
# boundary just as readily, so an exact-string replace is trivially bypassed.
_MARKER_RE = re.compile(r"UNTRUSTED\s+VIDEO\s+EVIDENCE", re.IGNORECASE)

# CommonMark and LLM readers treat all of these as line breaks; str.split("\n")
# does not, so a fence hidden behind one would evade a naive line scanner.
_LINE_BREAKS = ("\r\n", "\r", " ", " ", "\f", "\x85")


def sanitize_for_report(text: str) -> str:
    """Neutralize sequences in uploader-controlled text that could escape the
    report's structure when an agent reads it.

    Everything media-derived is attacker-controlled: the description, the title,
    the uploader name, and the transcript (manual captions are uploaded by the
    author). Without this, a description containing the END marker closes the
    untrusted block early and everything after it reads as trusted context.

    Three vectors:
      1. the BEGIN/END UNTRUSTED VIDEO EVIDENCE markers, matched loosely;
      2. lines opening a GFM fence (3+ backticks or tildes) -- the description
         is rendered inside a fence, so one would close it and let the rest
         render as report structure;
      3. fences hidden behind non-LF line terminators.

    ponytail: zero-width spaces, not deletion. The text stays readable and the
    exact spellings survive (the whole reason the description is in the report),
    but the token no longer reads as a marker or a fence.
    """
    for terminator in _LINE_BREAKS:
        text = text.replace(terminator, "\n")

    text = _MARKER_RE.sub(lambda m: ZWSP.join(m.group(0)), text)

    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            lines[i] = ZWSP + line
    return "\n".join(lines)


def format_description(info: dict, limit: int = DESCRIPTION_CHAR_LIMIT) -> str | None:
    """The author-supplied description, bounded, or None if there isn't one.

    Worth surfacing because ASR cannot spell: on a repo-roundup video the
    auto-captions recovered 1 of 13 repo names ("Omniroot" for OmniRoute), while
    the description carried all 13 verbatim for ~540 tokens. Links, product
    names, and URLs live here and nowhere else in the audio.

    It is author-controlled text, so callers must render it inside the report's
    untrusted-evidence markers and must never treat it as authoritative for what
    happens on screen. ponytail: a character cap, not a token count -- ~4 chars
    per token is close enough to keep a spam-stuffed description from crowding
    out the transcript.
    """
    body = (info.get("description") or "").strip()
    if not body:
        return None
    if len(body) > limit:
        body = body[:limit].rstrip() + f"\n\n[… truncated at {limit} characters]"
    # Sanitize last: truncation could otherwise slice a neutralized marker back
    # into a live one.
    return sanitize_for_report(body)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: download.py <url-or-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = download(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
