#!/usr/bin/env python3
"""Parse a WebVTT subtitle file into a clean, timestamped transcript.

YouTube auto-subs emit rolling-duplicate cues (each line appears 2-3 times as it
scrolls). We dedupe consecutive identical cues and merge their time ranges.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


TS_VALUE = r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})"
TS_RE = re.compile(rf"^\s*{TS_VALUE}\s+-->\s+{TS_VALUE}(?:\s+.*)?$")
TAG_RE = re.compile(r"<[^>]+>")

MIN_OVERLAP = 8


def _to_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


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
        while i < len(lines) and lines[i].strip():
            cleaned = TAG_RE.sub("", lines[i]).strip()
            if cleaned:
                cue_lines.append(cleaned)
            i += 1

        cue_text = " ".join(cue_lines).strip()
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
        stamp = f"[{start // 60:02d}:{start % 60:02d}]"
        lines.append(f"{stamp} {seg['text']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe.py <vtt-path>", file=sys.stderr)
        raise SystemExit(2)
    print(format_transcript(parse_vtt(sys.argv[1])))
