#!/usr/bin/env python3
"""Reproducible v1.5.5 release-verification harness.

Run from the repository root:  python3 docs/evidence/v1.5.5-video-cache/run-verification.py

Produces, in this directory: verify.json (commands, integer exit codes,
timings, environment, pre-release HEAD), hash-manifest.json (full media
sha256s and every paired frame hash for the cold and hit runs), and the
path-normalized cold-report.txt / hit-report.txt. Secret-free: no keys are
read or required (--no-whisper), the cache is purged before and after, and
all temporary work lives in a mkdtemp removed on exit.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
REPO = EVIDENCE_DIR.parents[2]
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def isolated_env(temp_home: Path) -> dict:
    """Allowlisted environment with an ISOLATED home: the harness must never
    read the user's WATCH_* configuration or credentials, and its purges must
    only ever touch the isolated cache under the temporary home."""
    # SYSTEMROOT/COMSPEC are Windows-required and inert elsewhere; the
    # isolation claim is: nothing user-specific, no WATCH_*, no credentials.
    allow = {"PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "SYSTEMROOT", "COMSPEC"}
    env = {k: v for k, v in os.environ.items() if k in allow}
    env["HOME"] = str(temp_home)
    env["USERPROFILE"] = str(temp_home)
    env["WATCH_VIDEO_CACHE"] = "1"
    return env


def run(cmd: list[str], env: dict, **kw) -> tuple[subprocess.CompletedProcess, float]:
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env, **kw)
    return proc, round(time.time() - t0, 1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    text = re.sub(r"/private/[^\s`]+", "<WORK>", text)
    text = re.sub(r"/Users/[^\s`]+", "<WORK>", text)
    text = re.sub(r"(?:[A-Za-z]:)?[\\/][^\s`]*[Tt]emp[\\/][^\s`]+", "<WORK>", text)
    return text


def main() -> int:
    receipts: dict = {}
    # Temporary root FIRST; every subprocess after this runs in the isolated
    # environment, so no purge or config read can ever touch real user state.
    # resolve(): macOS mkdtemp yields /var/… and /var is a symlink — the
    # cache's own ancestor-symlink refusal would (correctly) disable it.
    work = Path(tempfile.mkdtemp(prefix="v155-verify-")).resolve()
    temp_home = work / "home"
    temp_home.mkdir()
    env = isolated_env(temp_home)

    proc, _ = run([sys.executable, "-m", "pytest", "-q", "tests/test_video_cache.py"], env)
    receipts["cache_focused"] = {
        "cmd": "python3 -m pytest -q tests/test_video_cache.py",
        "exit": proc.returncode,
        "result": proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
    }
    proc, _ = run([sys.executable, "-m", "pytest", "-q"], env)
    receipts["full_suite"] = {
        "cmd": "python3 -m pytest -q",
        "exit": proc.returncode,
        "result": proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
    }
    proc, _ = run([sys.executable, "skills/watch/scripts/video_cache.py", "--purge"], env)
    receipts["purge_before"] = {
        "cmd": "WATCH_VIDEO_CACHE=1 python3 skills/watch/scripts/video_cache.py --purge (isolated HOME)",
        "exit": proc.returncode,
        "result": proc.stdout.strip(),
    }

    try:
        base = [sys.executable, "skills/watch/scripts/watch.py", URL,
                "--no-whisper", "--detail", "efficient"]
        cold_dir, hit_dir = work / "cold", work / "hit"
        proc_c, cold_secs = run([*base, "--out-dir", str(cold_dir)], env)
        proc_h, hit_secs = run([*base, "--out-dir", str(hit_dir)], env)
        banner_line = "[watch] serving media from the local video cache (verified, experimental)…"
        cold_marker_line = "- **Video cache (experimental):** miss — downloaded and stored"
        hit_marker_line = "- **Video cache (experimental):** hit — served checksum-verified local copy"
        download_line = "[watch] downloading video via yt-dlp…"

        def count_line(text: str, line: str) -> int:
            return text.splitlines().count(line)

        receipts["live_cold"] = {
            "cmd": f"WATCH_VIDEO_CACHE=1 python3 skills/watch/scripts/watch.py '{URL}' "
                   "--no-whisper --detail efficient --out-dir <mkdtemp>/cold",
            "exit": proc_c.returncode, "seconds": cold_secs,
            "downloads": count_line(proc_c.stderr, download_line),
            "download_line": download_line,
        }
        receipts["live_hit"] = {
            "cmd": f"WATCH_VIDEO_CACHE=1 python3 skills/watch/scripts/watch.py '{URL}' "
                   "--no-whisper --detail efficient --out-dir <mkdtemp>/hit",
            "exit": proc_h.returncode, "seconds": hit_secs,
            "downloads": count_line(proc_h.stderr, download_line),
            "stderr_banner": banner_line if count_line(proc_h.stderr, banner_line) == 1 else "MISSING",
            "report_marker": hit_marker_line if count_line(proc_h.stdout, hit_marker_line) == 1 else "MISSING",
        }
        receipts["live_cold"]["report_marker"] = (
            cold_marker_line if count_line(proc_c.stdout, cold_marker_line) == 1 else "MISSING"
        )

        cv = sorted(cold_dir.rglob("video.mp4"))[0]
        hv = sorted(hit_dir.rglob("video.mp4"))[0]
        cold_map = {p.name: sha256(p) for p in cold_dir.rglob("frame_*.jpg")}
        hit_map = {p.name: sha256(p) for p in hit_dir.rglob("frame_*.jpg")}
        manifest = {
            "hash_cmd": "hashlib.sha256(path.read_bytes()).hexdigest() over each "
                        "video.mp4 and every frame_*.jpg per run (this harness, sha256())",
            "media_sha256_cold": sha256(cv),
            "media_sha256_hit": sha256(hv),
            "cold_frame_count": len(cold_map),
            "hit_frame_count": len(hit_map),
            "frame_name_sets_identical": set(cold_map) == set(hit_map),
            "frames": [
                {"name": name, "cold_sha256": cold_map[name], "hit_sha256": hit_map.get(name, "ABSENT")}
                for name in sorted(cold_map)
            ],
        }
        manifest["media_identical"] = manifest["media_sha256_cold"] == manifest["media_sha256_hit"]
        manifest["all_frames_identical"] = (
            manifest["frame_name_sets_identical"]
            and bool(cold_map)
            and all(f["cold_sha256"] == f["hit_sha256"] for f in manifest["frames"])
        )
        (EVIDENCE_DIR / "hash-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        def scrub(text: str) -> str:
            # Normalize the ACTUAL allocated paths first, then the host-shape
            # fallbacks — never rely on host-specific regexes alone.
            text = text.replace(str(work), "<WORK>").replace(str(temp_home), "<HOME>")
            return normalize(text)

        (EVIDENCE_DIR / "cold-report.txt").write_text(scrub(proc_c.stdout), encoding="utf-8")
        (EVIDENCE_DIR / "hit-report.txt").write_text(scrub(proc_h.stdout), encoding="utf-8")

        def probe(argv: list[str]) -> str:
            result, _ = run(argv, env)
            return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""

        environment = {
            "macos_product": probe(["sw_vers", "-productVersion"]),
            "macos_build": probe(["sw_vers", "-buildVersion"]),
            "darwin": platform.release(),
            "python": platform.python_version(),
            "yt_dlp": probe(["yt-dlp", "--version"]),
            "ffmpeg": (probe(["ffmpeg", "-version"]).split() or ["", "", ""])[2],
        }
    finally:
        # Final purge BEFORE the temporary home disappears, and RECORDED.
        proc, _ = run([sys.executable, "skills/watch/scripts/video_cache.py", "--purge"], env)
        receipts["purge_after"] = {
            "cmd": "WATCH_VIDEO_CACHE=1 python3 skills/watch/scripts/video_cache.py --purge (isolated HOME)",
            "exit": proc.returncode,
            "result": proc.stdout.strip(),
        }
        shutil.rmtree(work, ignore_errors=True)

    verify = {
        "release": "1.5.5",
        "harness": "docs/evidence/v1.5.5-video-cache/run-verification.py",
        "commands": receipts,
        "environment": environment,
        "bundle": {"note": "dist/watch.skill is built by the release workflow from the "
                            "tagged commit (build-skill.sh refuses dirty trees); the released "
                            "asset's URL, HTTP status, and sha256 are appended to EXIT.md post-release"},
        "head_before_release": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO
        ).stdout.strip(),
    }
    (EVIDENCE_DIR / "verify.json").write_text(json.dumps(verify, indent=2) + "\n", encoding="utf-8")
    cold_names = {f["name"] for f in manifest["frames"]}
    ok = (
        all(r.get("exit") == 0 for r in receipts.values())
        and manifest["media_identical"] and manifest["all_frames_identical"]
        and manifest["cold_frame_count"] > 0
        and manifest["cold_frame_count"] == manifest["hit_frame_count"] == len(cold_names)
        and manifest["frame_name_sets_identical"]
        and receipts["live_cold"]["downloads"] == 1
        and receipts["live_hit"]["downloads"] == 0
        and receipts["live_hit"]["stderr_banner"] != "MISSING"
        and receipts["live_cold"]["report_marker"] != "MISSING"
        and receipts["live_hit"]["report_marker"] != "MISSING"
    )
    print(json.dumps({"ok": ok, **{k: v.get("exit") for k, v in receipts.items()}}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
