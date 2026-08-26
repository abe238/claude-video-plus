#!/usr/bin/env python3
"""v3 blind-spot MEASUREMENT (go/no-go gate before building v3).

Question: does the current DEFAULT engine (v2) drop distinct on-screen states
when the change between them is small (caption swap, a new bullet) — the blind
spot claude-real-video's benchmark measured? We build synthetic fixtures with a
KNOWN number of states, run the real v2 default extraction, and count how many
states survive. A positive control (hard cuts v2 must catch) validates the probe
per the owner's positive-control rule.

Metric: a state's 5s window is "captured" if >=1 kept frame lands in it.
"""
from __future__ import annotations

import re, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
FIX.mkdir(exist_ok=True)
ROOT = HERE.parents[2]
WATCH = ROOT / "skills" / "watch" / "scripts" / "watch.py"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
W, H, FPS, STATE_SECS = 640, 360, 10, 5


def font(sz):
    return ImageFont.truetype(FONT_PATH, sz)


def _encode(frames_dir: Path, out: Path, per_state: int):
    # each state is one PNG shown for STATE_SECS; ffmpeg reads them as a slideshow
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"1/{STATE_SECS}",
         "-i", str(frames_dir / "s%02d.png"), "-r", str(FPS), "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )


def gen_caption_swap(states):
    """Static gray bg + fixed title; only a small bottom caption changes."""
    d = FIX / "_cap"; d.mkdir(exist_ok=True)
    caps = ["mix the base", "heat gently", "let it cool", "pour slowly", "rest ten min", "serve warm"]
    for i in range(states):
        img = Image.new("RGB", (W, H), (128, 128, 128))
        dr = ImageDraw.Draw(img)
        dr.text((W / 2, 30), "RECIPE DEMO", font=font(30), fill=(0, 0, 0), anchor="mm")
        dr.rectangle([120, 150, 520, 210], outline=(60, 60, 60), width=3)  # fixed shape
        dr.text((W / 2, H - 40), f"step {i+1}: {caps[i]}", font=font(22), fill=(255, 255, 255), anchor="mm")
        img.save(d / f"s{i:02d}.png")
    _encode(d, FIX / "caption_swap.mp4", states)


def gen_ui_bullets(states):
    """A slide that gains one bullet per state (small additive change)."""
    d = FIX / "_ui"; d.mkdir(exist_ok=True)
    bullets = ["revenue up 12%", "churn down 3%", "NPS at 61", "2 new markets", "hiring 40", "runway 30mo"]
    for i in range(states):
        img = Image.new("RGB", (W, H), (250, 250, 250))
        dr = ImageDraw.Draw(img)
        dr.text((40, 30), "Q3 RESULTS", font=font(28), fill=(20, 20, 20))
        for j in range(i + 1):
            dr.text((60, 90 + j * 40), f"- {bullets[j]}", font=font(20), fill=(40, 40, 40))
        img.save(d / f"s{i:02d}.png")
    _encode(d, FIX / "ui_bullets.mp4", states)


def gen_positive_control(states):
    """Full-frame distinct color slides — big changes v2 MUST catch."""
    d = FIX / "_pc"; d.mkdir(exist_ok=True)
    for i in range(states):
        col = ((i * 40) % 256, (i * 70) % 256, (i * 90 + 30) % 256)
        img = Image.new("RGB", (W, H), col)
        ImageDraw.Draw(img).text((W / 2, H / 2), f"SLIDE {i+1}", font=font(48), fill=(255, 255, 255), anchor="mm")
        img.save(d / f"s{i:02d}.png")
    _encode(d, FIX / "positive_control.mp4", states)


FRAME_RE = re.compile(r"\(t=(\d+):(\d\d), reason=([a-z-]+)\)")


def kept_seconds(mp4: Path):
    out = subprocess.run([sys.executable, str(WATCH), str(mp4), "--no-whisper", "--detail", "balanced"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-500:]
    return [int(m) * 60 + int(s) for m, s, _ in FRAME_RE.findall(out.stdout)]


def states_covered(seconds, n_states):
    windows = set()
    for t in seconds:
        idx = min(int(t // STATE_SECS), n_states - 1)
        windows.add(idx)
    return sorted(windows)


def main():
    N = 6
    gen_caption_swap(N); gen_ui_bullets(N); gen_positive_control(N)
    results = {}
    for name in ("positive_control", "caption_swap", "ui_bullets"):
        secs = kept_seconds(FIX / f"{name}.mp4")
        cov = states_covered(secs, N)
        results[name] = {"states_present": N, "frames_kept": len(secs),
                         "states_captured": len(cov), "captured_windows": cov}
    print("\n=== v2 default: distinct-state capture ===")
    for name, r in results.items():
        miss = r["states_present"] - r["states_captured"]
        tag = "  <-- POSITIVE CONTROL" if name == "positive_control" else ""
        print(f"{name:18s}: {r['states_captured']}/{r['states_present']} states captured "
              f"({r['frames_kept']} frames kept, {miss} missed){tag}")
    return results


if __name__ == "__main__":
    main()
