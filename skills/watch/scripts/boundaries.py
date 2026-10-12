"""Structural boundaries for --boundary-anchors: fades, held frames, silences.

Scene-change scoring misses a slow fade (the change is spread over many frames)
and a held card (nothing changes). ffmpeg's state detectors report intervals
instead, so one cheap low-resolution decode (``-f null``, nothing written) finds
them. Idea credit: frinsen/claude-video (MIT); this is an independent
reimplementation.

Everything here fails open: any error yields ``([], note)``, never an exception.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from config import ffmpeg_timeout, run_bounded

PROBE_WIDTH = 160            # statistics survive a shrink; decoding small is the cheap part
MAX_BOUNDARIES = 200         # hard cap on what one pass may return
DEDUPE_SECONDS = 1.0         # boundaries closer than this collapse to the earliest
BLACK_MIN_DURATION = 0.10
BLACK_PIX_TH = 0.10
FREEZE_NOISE = "-60dB"
FREEZE_MIN_DURATION = 0.5
SILENCE_NOISE = "-30dB"
SILENCE_MIN_DURATION = 1.0
# Offsets so the pinned frame lands inside the new state, not on the edge.
BLACK_END_OFFSET = 0.25
FREEZE_START_OFFSET = 0.1

# Lower number wins when the cap forces a choice: fades, then held cards, then silences.
_PRIORITY = {"black-end": 0, "freeze-start": 1, "silence-end": 2}

_BLACK_RE = re.compile(r"black_start:\s*[-0-9.]+\s+black_end:\s*([0-9.]+)")
_FREEZE_RE = re.compile(r"freeze_start:\s*([0-9.]+)")
_SILENCE_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def parse_boundaries(log: str, offset: float = 0.0) -> list[tuple[float, str]]:
    """Pull ``(absolute_seconds, kind)`` marks out of ffmpeg stderr."""
    marks: list[tuple[float, str]] = []
    for rx, kind, shift in (
        (_BLACK_RE, "black-end", BLACK_END_OFFSET),
        (_FREEZE_RE, "freeze-start", FREEZE_START_OFFSET),
        (_SILENCE_RE, "silence-end", 0.0),
    ):
        for m in rx.finditer(log):
            try:
                marks.append((round(offset + float(m.group(1)) + shift, 2), kind))
            except ValueError:
                continue
    return marks


def cap_by_priority(marks: list[tuple[float, str]], limit: int) -> list[tuple[float, str]]:
    """Keep at most ``limit`` marks: all fades first, then held cards, then
    silences; within a kind the survivors are spread evenly. Chronological out."""
    if limit <= 0:
        return []
    kept: list[tuple[float, str]] = []
    for rank in sorted({_PRIORITY[k] for _, k in marks}):
        tier = sorted(m for m in marks if _PRIORITY[m[1]] == rank)
        room = limit - len(kept)
        if room <= 0:
            break
        if len(tier) > room:  # spread evenly, first and last kept
            tier = [tier[0]] if room == 1 else [
                tier[round(i * (len(tier) - 1) / (room - 1))] for i in range(room)]
        kept += tier
    return sorted(kept)


def select_boundaries(
    marks: list[tuple[float, str]],
    limit: int = MAX_BOUNDARIES,
    lo: float = 0.0,
    hi: float | None = None,
) -> list[tuple[float, str]]:
    """Window, dedupe within ``DEDUPE_SECONDS`` (keeping the higher-priority kind),
    cap to ``limit`` by priority, return chronological ``(seconds, kind)``."""
    limit = min(limit, MAX_BOUNDARIES)
    inside = [m for m in marks if m[0] >= lo and (hi is None or m[0] <= hi)]
    kept: list[tuple[float, str]] = []
    anchor = 0.0  # time of the first mark of the current cluster (no drift)
    for t, kind in sorted(inside):
        if kept and t - anchor < DEDUPE_SECONDS:
            if _PRIORITY[kind] < _PRIORITY[kept[-1][1]]:
                kept[-1] = (t, kind)
            continue
        kept.append((t, kind))
        anchor = t
    return cap_by_priority(kept, limit)


def detect_boundaries(
    video_path: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    duration: float | None = None,
    has_audio: bool = True,
    limit: int = MAX_BOUNDARIES,
) -> tuple[list[tuple[float, str]], str | None]:
    """One ffmpeg pass -> ``([(seconds, kind)], note)``. Never raises."""
    try:
        if shutil.which("ffmpeg") is None:
            return [], "ffmpeg not installed"
        lo = start_seconds or 0.0
        top = end_seconds if end_seconds is not None else duration
        span = (top - lo) if top is not None else None
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info"]
        if start_seconds is not None:
            cmd += ["-ss", f"{start_seconds:.3f}"]
        if end_seconds is not None:
            cmd += ["-to", f"{end_seconds:.3f}"]
        cmd += ["-i", str(Path(video_path).resolve()), "-vf",
                f"scale={PROBE_WIDTH}:-2,blackdetect=d={BLACK_MIN_DURATION}:pix_th={BLACK_PIX_TH},"
                f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_DURATION}"]
        if has_audio:  # -af on a file with no audio stream makes ffmpeg exit 1
            cmd += ["-af", f"silencedetect=n={SILENCE_NOISE}:d={SILENCE_MIN_DURATION}"]
        cmd += ["-f", "null", "-"]
        res = run_bounded(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=ffmpeg_timeout(span))
        if res.returncode != 0:  # includes 124 = timed out
            return [], f"ffmpeg exited {res.returncode}: {(res.stderr or '').strip()[-200:]}"
        marks = parse_boundaries(res.stderr or "", lo)
        return select_boundaries(marks, limit, lo, end_seconds), None
    except Exception as exc:  # fail open: a boundary pass must never brick a run
        return [], f"{type(exc).__name__}: {exc}"
