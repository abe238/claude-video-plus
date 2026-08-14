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
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from acquisition import (
    AcquisitionAttempt,
    ytdlp_cmd,
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
        # Exact-language track before the "-orig" ASR track: when both exist the
        # exact one is the human-written upload, and ASR garbles proper nouns
        # ("jillian lynn" for Gillian Lynne), which starves lexical retrieval.
        exact: list[Path] = []
        asr_orig: list[Path] = []
        for candidate in candidates:
            name = candidate.name.lower()
            if candidate in ordered:
                continue
            if f".{language.lower()}." in name or f".{base}." in name:
                exact.append(candidate)
            elif f".{base}-orig." in name:
                asr_orig.append(candidate)
        ordered.extend(exact + asr_orig)
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
    if shutil.which("yt-dlp") is None and ytdlp_cmd() == ("yt-dlp",):
        raise SystemExit(
            "yt-dlp is not usable. Install with: brew install yt-dlp "
            "(or pip install yt-dlp so `python -m yt_dlp` works)"
        )

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
    if shutil.which("yt-dlp") is None and ytdlp_cmd() == ("yt-dlp",):
        raise SystemExit(
            "yt-dlp is not usable. Install with: brew install yt-dlp "
            "(or pip install yt-dlp so `python -m yt_dlp` works)"
        )

    cfg = acquisition_config(read_env_file())
    result = acquire_url(
        url, out_dir, audio_only=audio_only,
        languages=cfg["languages"], cookie_spec=cfg["cookie_spec"],
        max_filesize=cfg["max_filesize"],
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

# Code points that render as NOTHING but read as text to a model. They are the
# gap between what the user sees in the report and what the agent consumes, so
# an uploader can hide instructions in a description or a caption track that are
# invisible to the human approving the answer. Stripped, never zero-width-padded
# (there is no spelling to preserve inside a character that has no glyph).
_INVISIBLE_CODEPOINTS = frozenset({
    # Zero-width spacers and joiners.
    0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x034F, 0x180E,
    0x2061, 0x2062, 0x2063, 0x2064,
    # Bidi embeddings/overrides/isolates — the Trojan Source class
    # (CVE-2021-42574): these do not change the characters a model reads, they
    # change the order a human SEES, so reviewer and agent disagree about the
    # same line. Legitimate Arabic/Hebrew is unaffected: the Unicode Bidi
    # Algorithm derives direction from the characters themselves.
    0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
    # Blank-width *letters* — not format controls, so a category filter misses
    # them, and they survive whitespace normalization.
    0x115F, 0x1160, 0x3164, 0xFFA0,
})
# The Unicode tag block: originally language tags, now used to smuggle a whole
# ASCII payload as invisible characters (chr(0xE0000 + ord(c)) per letter).
_TAG_BLOCK = range(0xE0000, 0xE0080)


# Variation selectors. VS1-16 (Mn, so a category filter for format chars misses
# them) and VS17-256 each carry a byte, giving the same arbitrary-payload channel
# as the tag block. Verified: a 10-byte payload round-tripped through VS17+.
_VARIATION_SELECTORS = frozenset(range(0xFE00, 0xFE10)) | frozenset(range(0xE0100, 0xE01F0))

# ZWJ and ZWNJ are the only two invisibles with legitimate *semantic* use in
# prose: ZWJ joins emoji (👨‍💻) and ZWNJ is a required half-space in Persian
# (می‌رود) and affects Indic conjuncts. Stripping them unconditionally corrupts
# real titles and descriptions, so they are kept only where they can be doing
# that job — between two non-ASCII characters. Between ASCII they can only be
# evasion padding ("SYS<ZWJ>TEM"), so they go.
_CONTEXTUAL = {0x200C, 0x200D}


def strip_invisible(text: str) -> tuple[str, int]:
    """Drop code points that render as nothing. Returns (text, removed_count).

    Category ``Cf`` (format) is stripped wholesale rather than by enumeration:
    it covers zero-width spacers, bidi controls, the tag block, the deprecated
    U+206A-206F formatting characters, and — critically — anything Unicode adds
    later. An enumerated denylist silently reopens this hole on every new
    Unicode revision, which is how U+206A slipped past the first version of
    this function and left the UNTRUSTED-marker defense bypassable.
    """
    kept: list[str] = []
    removed = 0
    for i, ch in enumerate(text):
        code = ord(ch)
        if code in _CONTEXTUAL:
            prev_ch = text[i - 1] if i else ""
            next_ch = text[i + 1] if i + 1 < len(text) else ""
            if prev_ch and next_ch and ord(prev_ch) > 0x7F and ord(next_ch) > 0x7F:
                kept.append(ch)      # joining emoji or Arabic/Indic letters
                continue
            removed += 1
            continue
        if (unicodedata.category(ch) == "Cf"
                or code in _INVISIBLE_CODEPOINTS
                or code in _TAG_BLOCK
                or code in _VARIATION_SELECTORS):
            removed += 1
            continue
        kept.append(ch)
    return "".join(kept), removed


def sanitize_for_report(text: str) -> str:
    """Neutralize sequences in uploader-controlled text that could escape the
    report's structure when an agent reads it.

    Everything media-derived is attacker-controlled: the description, the title,
    the uploader name, and the transcript (manual captions are uploaded by the
    author). Without this, a description containing the END marker closes the
    untrusted block early and everything after it reads as trusted context.

    Four vectors:
      0. invisible code points (zero-width, bidi overrides, blank-width letters,
         the Unicode tag block) -- text the human reviewer cannot see but the
         agent reads verbatim. Stripped FIRST, before the defenses below add
         their own zero-width padding;
      1. the BEGIN/END UNTRUSTED VIDEO EVIDENCE markers, matched loosely;
      2. lines opening a GFM fence (3+ backticks or tildes) -- the description
         is rendered inside a fence, so one would close it and let the rest
         render as report structure;
      3. fences hidden behind non-LF line terminators.

    ponytail: zero-width spaces, not deletion, for vectors 1-3. The text stays
    readable and the exact spellings survive (the whole reason the description
    is in the report), but the token no longer reads as a marker or a fence.
    Vector 0 is the exception: an invisible character has no spelling to keep.
    """
    text, _ = strip_invisible(text)

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
