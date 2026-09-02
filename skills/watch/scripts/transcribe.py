#!/usr/bin/env python3
"""Parse a WebVTT subtitle file into a clean, timestamped transcript.

YouTube auto-subs emit rolling-duplicate cues (each line appears 2-3 times as it
scrolls). We dedupe consecutive identical cues and merge their time ranges.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from download import strip_invisible


TS_VALUE = r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})"
TS_RE = re.compile(rf"^\s*{TS_VALUE}\s+-->\s+{TS_VALUE}(?:\s+.*)?$")
TAG_RE = re.compile(r"<[^>]+>")
# WebVTT voice span: `<v Alex Chen>text</v>` (optionally `<v.loud Alex>`). Teams,
# Zoom and Meet exports carry the speaker name here; the generic TAG_RE strip
# below would discard it, so lift the name out first to keep "who said what".
# (fork-watch: donlapidos.) The name is untrusted caption text — length-capped
# here and defused again at the report chokepoint (sanitize_for_report).
#
# The class-token char class EXCLUDES `.` (`[^\s>.]`, not `[^\s>]`): a class is
# dot-delimited (`.loud.fast`), and letting it swallow `.` made the `(?:…)*`
# ambiguous → catastrophic backtracking (ReDoS) on a crafted `<v.a.a.a…` line
# with no close. With no-dot class bodies the groups are fixed and matching is
# linear; the search is also windowed to the line head where a real `<v>` sits.
VOICE_RE = re.compile(r"<v(?:\.[^\s>.]+)*\s+([^>]+?)\s*>", re.IGNORECASE)
_MAX_SPEAKER_CHARS = 80
_VOICE_SEARCH_WINDOW = 256  # a real voice tag opens the cue line; bound the scan

MIN_OVERLAP = 8


def _to_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _decode_entities(text: str) -> str:
    """Decode HTML entities in caption cue text, then re-apply the invisible-
    character policy to whatever the decode produced.

    YouTube VTT/json3 tracks carry `&amp;`, `&nbsp;` and friends verbatim
    (upstream PR #124, Ydiouri, via the bugsmithd fork audit). Unescape runs
    exactly ONCE — `&amp;amp;` must yield the literal `&amp;`, never a second
    decode. NBSP folds to a plain space. Because a numeric entity can smuggle
    any code point past upstream byte-level filters (`&#8206;` → bidi mark),
    the decoded text goes through download.strip_invisible — the single
    context-aware policy (category-based Cf strip, contextual ZWJ/ZWNJ
    preservation for Persian/Indic/emoji) — rather than any local list.
    """
    decoded = html.unescape(text).replace("\u00a0", " ")
    cleaned, _removed = strip_invisible(decoded)
    return cleaned


def parse_subtitle(path: str | Path, *, strict: bool = False) -> list[dict]:
    """Parse WebVTT or SubRip into the legacy timestamped-segment shape.

    ``strict`` is used for user-supplied sidecars: malformed UTF-8 or a file
    containing cue text but no valid timestamps is rejected instead of silently
    becoming an empty transcript.  Native-caption compatibility keeps the old
    forgiving behavior through :func:`parse_vtt`.
    """
    subtitle_path = Path(path)
    text = subtitle_path.read_text(encoding="utf-8", errors="strict" if strict else "ignore")
    lines = text.splitlines()

    segments: list[dict] = []
    prev_speaker: str | None = None
    i = 0
    while i < len(lines):
        match = TS_RE.match(lines[i])
        if not match:
            i += 1
            continue

        start = _to_seconds(*match.groups()[:4])
        end = _to_seconds(*match.groups()[4:])
        if end < start:
            if strict:
                raise ValueError(f"subtitle cue ends before it starts in {subtitle_path.name}")
            i += 1
            continue
        i += 1

        cue_lines: list[str] = []
        speaker: str | None = None
        while i < len(lines) and lines[i].strip():
            raw = lines[i]
            # ponytail: first voice tag in the cue wins. A legal multi-voice cue
            # (`<v Alex>Hi</v> <v Beau>Bye</v>`) attributes all of it to Alex —
            # rare in Teams/Zoom exports (one voice per cue). Upgrade to
            # per-span attribution only if a real multi-voice track shows up.
            if speaker is None:
                voice = VOICE_RE.search(raw[:_VOICE_SEARCH_WINDOW])
                if voice:
                    name = _decode_entities(voice.group(1)).strip()[:_MAX_SPEAKER_CHARS]
                    if name:
                        speaker = name
            cleaned = TAG_RE.sub("", raw).strip()
            if cleaned:
                cue_lines.append(cleaned)
            i += 1

        cue_text = _decode_entities(" ".join(cue_lines)).strip()
        # Label only on a speaker CHANGE (a real transcript, not "Alex:" on every
        # line) so meeting recordings stay answerable for "who said what" at
        # near-zero token cost. The prefix is defused as data at the report.
        if speaker and cue_text:
            if speaker != prev_speaker and not cue_text.startswith(f"{speaker}:"):
                cue_text = f"{speaker}: {cue_text}"
            prev_speaker = speaker
        if cue_text:
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": cue_text})
        i += 1

    result = dedupe_rolling(_dedupe(segments))
    if strict and text.strip() and not result:
        raise ValueError(f"no valid timestamped cues in {subtitle_path.name}")
    return result


def parse_vtt(path: str) -> list[dict]:
    return parse_subtitle(path)


def parse_srt(path: str) -> list[dict]:
    return parse_subtitle(path)


def _dedupe(segments: list[dict]) -> list[dict]:
    """Collapse exact repeats and prefix-growth common in YouTube auto-subs."""
    out: list[dict] = []
    for seg in segments:
        if out and seg["text"] == out[-1]["text"]:
            out[-1]["end"] = seg["end"]
            continue
        if out and seg["text"].startswith(out[-1]["text"] + " "):
            out[-1]["text"] = seg["text"]
            out[-1]["end"] = seg["end"]
            continue
        out.append(seg)
    return out


def strip_overlap(prev: str, cur: str) -> str:
    """Drop cur's leading words that repeat prev's tail (rolling captions
    re-emit the previous line as the next cue's first line). ponytail: a
    genuine >=8-char word-aligned self-repeat across a cue boundary would be
    stripped too; rare enough to accept."""
    for k in range(min(len(prev), len(cur)), MIN_OVERLAP - 1, -1):
        if (k == len(cur) or cur[k] == " ") and prev.endswith(cur[:k]):
            return cur[k:].lstrip()
    return cur


def dedupe_rolling(segments: list[dict]) -> list[dict]:
    """Collapse rolling-caption overlap left over after _dedupe's exact-dup
    pass: drop a cue contained in the previous one or whose first half is the
    previous cue's tail, and strip any shorter repeated prefix. Merges a fully
    dropped cue's time range into the keeper."""
    clean: list[dict] = []
    for seg in segments:
        text = seg["text"]
        if clean:
            prev = clean[-1]["text"]
            half = text[: len(text) // 2]
            if text in prev or (half and prev.endswith(half)):
                clean[-1]["end"] = max(clean[-1]["end"], seg["end"])
                continue
            text = strip_overlap(prev, text)
            if not text:
                clean[-1]["end"] = max(clean[-1]["end"], seg["end"])
                continue
        kept = dict(seg)
        kept["text"] = text
        clean.append(kept)
    return clean


def filter_range(
    segments: list[dict],
    start_seconds: float | None,
    end_seconds: float | None,
) -> list[dict]:
    """Return segments whose time range overlaps [start, end]."""
    if start_seconds is None and end_seconds is None:
        return segments
    lo = start_seconds if start_seconds is not None else float("-inf")
    hi = end_seconds if end_seconds is not None else float("inf")
    return [seg for seg in segments if seg["end"] >= lo and seg["start"] <= hi]


def format_transcript(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        start = int(seg["start"])
        # Past an hour the minutes field rolls over ([1:01:01], never [61:01]):
        # long talks are a core use case and an unparseable stamp isn't evidence
        # (upstream PR #88, dvirarad, via the bugsmithd fork audit).
        if start >= 3600:
            stamp = f"[{start // 3600}:{start % 3600 // 60:02d}:{start % 60:02d}]"
        else:
            stamp = f"[{start // 60:02d}:{start % 60:02d}]"
        lines.append(f"{stamp} {seg['text']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe.py <vtt-path>", file=sys.stderr)
        raise SystemExit(2)
    print(format_transcript(parse_vtt(sys.argv[1])))
