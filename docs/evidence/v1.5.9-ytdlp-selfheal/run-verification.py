#!/usr/bin/env python3
"""Deterministic verification for v1.5.9 yt-dlp self-heal (no network for the
logic; one live upgrade probe against the local pip/yt-dlp).

Proves, via the focused suite and a live call:
  - hardened, isolated, official-index, fixed pip argv (no injection surface);
  - upgrade latched at most once per process;
  - rc=0-but-unrunnable module is not trusted;
  - .env opt-out honored through the production download_url wiring;
  - a still-fatal retry preserves the original actionable (http_403) error;
  - the real upgrade_ytdlp() runs end-to-end and forces a runnable module.
Emits verify.json next to this file.
"""
from __future__ import annotations

import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def pytest(expr):
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", *expr], cwd=ROOT,
                       capture_output=True, text=True)
    return {"cmd": "pytest -q " + " ".join(expr), "exit": p.returncode,
            "result": (p.stdout.strip().splitlines() or [""])[-1]}


results = {"release": "1.5.9", "harness": str(HERE / "run-verification.py"), "checks": {}}

# Focused self-heal + Windows-fallback + full suites.
results["checks"]["selfheal_tests"] = pytest([
    "tests/test_acquisition.py", "-k", "ytdlp or self_heal or selfheal or upgrade or optout"])
results["checks"]["windows_fallback_tests"] = pytest(["tests/test_windows_resilience.py"])
results["checks"]["full_suite"] = pytest([])
for name, c in results["checks"].items():
    assert c["exit"] == 0, f"{name}: {c}"

# Live proof: the real upgrade_ytdlp() runs and forces a runnable module.
live = subprocess.run([sys.executable, "-c", (
    "import sys; sys.path.insert(0, 'skills/watch/scripts'); import acquisition, subprocess;"
    "ok = acquisition.upgrade_ytdlp();"
    "cmd = acquisition.ytdlp_cmd();"
    "r = subprocess.run([*cmd, '--version'], capture_output=True, text=True);"
    "print(ok, r.returncode, r.stdout.strip(), '|', ' '.join(cmd[1:]) )"
)], cwd=ROOT, capture_output=True, text=True)
results["checks"]["live_upgrade"] = {"cmd": "upgrade_ytdlp() + forced -m yt_dlp --version",
                                     "exit": live.returncode, "result": live.stdout.strip()}
assert live.returncode == 0 and live.stdout.split()[0] == "True", live.stdout + live.stderr

# Environment + pre-release HEAD.
ff = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
yt = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
results["environment"] = {"python": sys.version.split()[0], "platform": sys.platform,
                          "ffmpeg": (ff.stdout.splitlines() or [""])[0], "yt_dlp": yt.stdout.strip()}
results["pre_release_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                             capture_output=True, text=True).stdout.strip()

(HERE / "verify.json").write_text(json.dumps(results, indent=2) + "\n")
print("OK — verify.json written")
print(json.dumps(results["checks"], indent=2))
