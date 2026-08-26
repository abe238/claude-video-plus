#!/usr/bin/env python3
"""Deterministic verification for v1.5.8 --text-anchors (no network).

Feature-specific control arm (per the Codex gpt-5.6-sol Standards finding): the
flag adds NO scoring logic to the default selection path — every change is gated
behind `text_anchors_active`. This harness proves that property mechanically:

  ARM A — default selection (no flag) on a synthesized clip.
  ARM B — the SAME clip with --text-anchors, but no caption track (a local file),
          so the flag fails open. A and B MUST produce byte-identical frame
          selection; any difference would mean the flag perturbs the default
          path. This is the "no default-path regression vs the pre-feature
          engine" measurement for an additive, default-off flag.
  ARM C — manual --timestamps precedence: cue frames appear and are reserved
          against the cap (the wiring the live URL run in EVIDENCE.md exercises
          end-to-end with real captions).

Run: python3 docs/evidence/v1.5.8-text-anchors/run-verification.py
Emits verify.json next to this file.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WATCH = ROOT / "skills" / "watch" / "scripts" / "watch.py"
HERE = Path(__file__).resolve().parent

FRAME_RE = re.compile(r"\(t=([0-9:]+), reason=([a-z-]+)\)")


def synth_clip(path: Path) -> None:
    """A 12s clip with hard scene cuts every 3s (testsrc changes content)."""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=12",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def run_watch(clip: Path, *args: str) -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, str(WATCH), str(clip), "--no-whisper", *args],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


def frame_times(report: str) -> list[str]:
    return FRAME_RE.findall(report)


def main() -> int:
    results: dict = {"release": "1.5.8", "harness": str(HERE / "run-verification.py"), "arms": {}}
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "clip.mp4"
        synth_clip(clip)

        # ARM A/B — additive-only: default vs --text-anchors (no captions).
        a, _ = run_watch(clip, "--detail", "balanced")
        b, b_err = run_watch(clip, "--detail", "balanced", "--text-anchors")
        a_t, b_t = frame_times(a), frame_times(b)
        assert "no caption track available" in b_err, "expected fail-open note in ARM B"
        assert a_t == b_t, f"default path perturbed by flag: {a_t} != {b_t}"
        results["arms"]["A_default_vs_B_anchors_no_captions"] = {
            "frames_default": a_t,
            "frames_anchored_no_captions": b_t,
            "identical": a_t == b_t,
            "fail_open_note": "no caption track available" in b_err,
        }

        # ARM C — manual --timestamps reserve cue frames against the cap.
        c, _ = run_watch(clip, "--detail", "balanced", "--max-frames", "6", "--timestamps", "1,5")
        c_frames = frame_times(c)  # (time, reason) for every listed frame, cue included
        cue = sum(1 for _, reason in c_frames if reason == "transcript-cue")
        total = len(c_frames)
        assert cue == 2, f"expected 2 manual cue frames, got {cue}"
        assert total <= 6, f"cap exceeded: {total}"
        results["arms"]["C_manual_timestamps"] = {
            "cue_frames": cue, "total_frames": total, "cap": 6, "cap_respected": total <= 6,
        }

    # Focused + FULL suites (PROTOCOL requires a full-suite receipt).
    for name, cmd in (
        ("text_anchor_tests", [sys.executable, "-m", "pytest", "-q", "tests/test_text_anchors.py"]),
        ("acquisition_tests", [sys.executable, "-m", "pytest", "-q", "tests/test_acquisition.py"]),
        ("full_suite", [sys.executable, "-m", "pytest", "-q"]),
    ):
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        results["arms"][name] = {"cmd": " ".join(cmd[1:]), "exit": proc.returncode,
                                 "result": proc.stdout.strip().splitlines()[-1] if proc.stdout else ""}
        assert proc.returncode == 0, proc.stdout + proc.stderr

    # Environment (PROTOCOL: commands, exit codes, ENVIRONMENT, pre-release HEAD).
    ff = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    ytv = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
    results["environment"] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "ffmpeg": (ff.stdout.splitlines() or [""])[0],
        "yt_dlp": ytv.stdout.strip(),
    }
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    results["pre_release_head"] = head.stdout.strip()
    (HERE / "verify.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("OK — verify.json written")
    print(json.dumps(results["arms"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
