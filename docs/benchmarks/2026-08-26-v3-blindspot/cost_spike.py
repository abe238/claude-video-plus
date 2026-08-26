#!/usr/bin/env python3
"""v3 cost/feasibility spike: does a LARGER dedup signature recover the dropped
states, and is it cheap in pure stdlib (no Pillow at runtime)?

For each signature size, extract NxN grayscale frame thumbnails via ONE ffmpeg
pass (C-speed, same mechanism v2 already uses at 16x16), then run v2's own
windowed changed-cell dedup in pure Python and measure states-captured, frames
kept, and Python wall time. 16 is today's default (the blind spot); 32/64 are
candidates.
"""
from __future__ import annotations

import subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
FPS, STATE_SECS, N_STATES = 10, 5, 6
CELL_TOL = 25       # v2 V2_CELL_TOLERANCE
CHANGED_PCT = 2.0   # v2 V2_CHANGED_PCT_THRESHOLD
WINDOW = 4          # v2 V2_WINDOW_SIZE


def thumbs(mp4: Path, size: int):
    """One ffmpeg pass → raw NxN grayscale bytes per decoded frame."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
         "-vf", f"fps={FPS},scale={size}:{size},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True)
    raw = proc.stdout
    step = size * size
    return [raw[i:i + step] for i in range(0, len(raw), step)]


def changed_pct(a: bytes, b: bytes) -> float:
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > CELL_TOL)
    return 100.0 * changed / len(a)


def dedup(frames, size):
    """v2-style windowed changed-cell dedup, pure Python. Returns kept indices."""
    kept_idx, kept_sig = [], []
    for i, sig in enumerate(frames):
        if not kept_sig:
            kept_idx.append(i); kept_sig.append(sig); continue
        # duplicate if it is near-identical to ANY of the last WINDOW kept frames
        dup = any(changed_pct(sig, k) <= CHANGED_PCT for k in kept_sig[-WINDOW:])
        if not dup:
            kept_idx.append(i); kept_sig.append(sig)
    return kept_idx


def states_of(indices):
    return sorted({min(int((i / FPS) // STATE_SECS), N_STATES - 1) for i in indices})


def main():
    for name in ("caption_swap", "ui_bullets", "positive_control"):
        print(f"\n=== {name} ===")
        for size in (16, 32, 64):
            frames = thumbs(FIX / f"{name}.mp4", size)
            t0 = time.perf_counter()
            kept = dedup(frames, size)
            dt = (time.perf_counter() - t0) * 1000
            cov = states_of(kept)
            note = " (today's default)" if size == 16 else ""
            print(f"  {size:2d}px: {len(cov)}/{N_STATES} states, {len(kept):2d} frames kept, "
                  f"dedup {dt:5.1f} ms over {len(frames)} thumbs{note}")


if __name__ == "__main__":
    main()
