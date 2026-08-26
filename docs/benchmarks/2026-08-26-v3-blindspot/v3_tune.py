#!/usr/bin/env python3
"""Tune a v3 local-rescue detector against the corpus (must recover states) AND
a real clip (must not over-keep vs v2). Ports of v2's constants are reused; v3
adds: when the global comparator calls a frame duplicate, RESCUE it if a local
region differs strongly from the window (the caption/UI block).
"""
from __future__ import annotations

import subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
REAL = Path("/private/tmp/claude-501/-Users-abediaz/a5d0488d-5e1d-4365-9acd-940bca550fe5/scratchpad/bench-videos")
FPS, STATE_SECS, N = 10, 5, 6
CELL_TOL = 25
GLOBAL_DUP_PCT = 2.0   # v2 V2_CHANGED_PCT_THRESHOLD
WINDOW = 4


def thumbs(mp4, size):
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
        "-vf", f"fps={FPS},scale={size}:{size},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    step = size * size
    return [raw[i:i + step] for i in range(0, len(raw), step)]


def global_dup(a, b):
    ch = sum(1 for x, y in zip(a, b) if abs(x - y) > CELL_TOL)
    return ch * 100.0 / len(a) <= GLOBAL_DUP_PCT


def strip_rescue(a, b, size, strips, keep_frac, tol):
    """Local signal by horizontal strips (captions/UI live on rows): keep if any
    strip has >= keep_frac of its cells changed by > tol. A lower tol than the
    global comparator catches thin anti-aliased text that averages below 25."""
    sh = max(1, size // strips)
    for sy in range(0, size, sh):
        changed = 0
        for y in range(sy, min(sy + sh, size)):
            row = y * size
            changed += sum(1 for x in range(size) if abs(a[row + x] - b[row + x]) > tol)
        if changed / (sh * size) >= keep_frac:
            return True
    return False


def dedup_v3(frames, size, strips, keep_frac, tol):
    kept_i, win = [], []
    for i, sig in enumerate(frames):
        if not win:
            kept_i.append(i); win.append(sig); continue
        dup = all(global_dup(sig, k) for k in win[-WINDOW:])
        rescued = dup and all(strip_rescue(sig, k, size, strips, keep_frac, tol) for k in win[-WINDOW:])
        if not dup or rescued:
            kept_i.append(i); win.append(sig)
    return kept_i


def states_of(idx):
    return len({min(int((i / FPS) // STATE_SECS), N - 1) for i in idx})


def _v2_only(frames):
    win = []
    for sig in frames:
        if not win or not all(global_dup(sig, k) for k in win[-WINDOW:]):
            win.append(sig)
    return len(win)


def main():
    real = REAL / "ZDa-Z5JzLYM.mp4"  # static screencast — the real over-keep risk
    real_t = {}
    for size, strips, keep, tol in [(64, 16, 0.06, 12), (96, 16, 0.05, 12),
                                    (128, 16, 0.05, 12), (128, 32, 0.06, 12),
                                    (128, 32, 0.05, 10), (128, 32, 0.08, 10)]:
        cov = {}
        t0 = time.perf_counter()
        for name in ("caption_swap", "ui_bullets", "positive_control"):
            f = thumbs(FIX / f"{name}.mp4", size)
            cov[name] = states_of(dedup_v3(f, size, strips, keep, tol))
        if size not in real_t and real.exists():
            real_t[size] = thumbs(real, size)
        rf = real_t.get(size, [])
        v3k = len(dedup_v3(rf, size, strips, keep, tol)) if rf else -1
        v2k = _v2_only(rf) if rf else 1
        dt = time.perf_counter() - t0
        print(f"size={size} strips={strips} keep={keep:.0%} tol={tol}: "
              f"cap {cov['caption_swap']}/6 ui {cov['ui_bullets']}/6 pc {cov['positive_control']}/6 "
              f"| real-screencast v3={v3k} v2={v2k} (x{v3k/max(1,v2k):.1f}) [{dt:.1f}s]")


if __name__ == "__main__":
    main()
