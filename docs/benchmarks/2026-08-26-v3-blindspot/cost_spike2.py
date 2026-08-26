#!/usr/bin/env python3
"""v3 cost spike #2: the LOCAL-region detector (crv "settled-local" idea).

A global %-changed-cells threshold can't see a caption (it is <2% of frame
area at any resolution). The fix is to look for a BLOCK that differs strongly:
split the NxN signature into BxB blocks and keep a frame when any block's
changed-cell density (vs every kept frame in the window) exceeds a threshold.
This is a localized detector, still one ffmpeg pass + pure-Python scoring.
"""
from __future__ import annotations

import subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
FPS, STATE_SECS, N_STATES = 10, 5, 6
CELL_TOL = 25       # per-cell delta that marks a cell "changed" (v2's value)
WINDOW = 4


def thumbs(mp4: Path, size: int):
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
         "-vf", f"fps={FPS},scale={size}:{size},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True)
    raw = proc.stdout
    step = size * size
    return [raw[i:i + step] for i in range(0, len(raw), step)]


def max_block_change(a, b, size, block):
    """Max over all BxB blocks of the fraction of cells changed > CELL_TOL."""
    worst = 0.0
    nb = size // block
    for by in range(nb):
        for bx in range(nb):
            changed = 0
            for y in range(by * block, by * block + block):
                row = y * size
                for x in range(bx * block, bx * block + block):
                    if abs(a[row + x] - b[row + x]) > CELL_TOL:
                        changed += 1
            frac = changed / (block * block)
            if frac > worst:
                worst = frac
    return worst


def dedup_local(frames, size, block, keep_frac):
    kept_idx, kept_sig = [], []
    for i, sig in enumerate(frames):
        if not kept_sig:
            kept_idx.append(i); kept_sig.append(sig); continue
        # keep if it differs from EVERY windowed kept frame by a strong local block
        distinct = all(max_block_change(sig, k, size, block) >= keep_frac
                       for k in kept_sig[-WINDOW:])
        if distinct:
            kept_idx.append(i); kept_sig.append(sig)
    return kept_idx


def states_of(indices):
    return sorted({min(int((i / FPS) // STATE_SECS), N_STATES - 1) for i in indices})


def main():
    # 64px signature, 8x8 blocks (64 cells each), keep when a block is >=50% changed.
    SIZE, BLOCK, KEEP = 64, 8, 0.50
    print(f"local detector: {SIZE}px sig, {BLOCK}x{BLOCK} blocks, keep if a block >= {KEEP:.0%} changed\n")
    for name in ("caption_swap", "ui_bullets", "positive_control"):
        frames = thumbs(FIX / f"{name}.mp4", SIZE)
        t0 = time.perf_counter()
        kept = dedup_local(frames, SIZE, BLOCK, KEEP)
        dt = (time.perf_counter() - t0) * 1000
        cov = states_of(kept)
        tag = "  <-- POSITIVE CONTROL" if name == "positive_control" else ""
        print(f"  {name:18s}: {len(cov)}/{N_STATES} states, {len(kept):2d} frames kept, "
              f"{dt:5.1f} ms over {len(frames)} thumbs{tag}")


if __name__ == "__main__":
    main()
