#!/usr/bin/env python3
"""Fail-closed v1 release assembly audit; never publishes by itself."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_TESTS = ["tests/test_control_harness.py", "tests/test_control_conformance.py"]
MEDIA_TESTS = ["tests/test_dedup.py", "tests/test_fixtures.py", "tests/test_frames.py",
               "tests/test_timestamps.py", "tests/test_watch.py", "tests/test_whisper.py"]


def run(command: list[str]) -> dict:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return {"command": command, "exit": result.returncode,
            "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}


def versions() -> dict:
    skill = (ROOT / "skills/watch/SKILL.md").read_text(encoding="utf-8")
    skill_version = re.search(r'^\s*version: ["\']?([^"\'\n]+)', skill, re.M).group(1)
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())["version"]
    return {"skill": skill_version, "claude": claude, "codex": codex, "coherent": len({skill_version, claude, codex}) == 1}


def artifact(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        bad = [name for name in names if name != "watch/SKILL.md" and not re.fullmatch(r"watch/scripts/[a-z_]+\.py", name)]
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "files": names,
            "valid": names.count("watch/SKILL.md") == 1 and not bad and path.stat().st_size < 250 * 1024}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    all_tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*.py"))
    fast_tests = [path for path in all_tests if path not in CONTROL_TESTS and path not in MEDIA_TESTS]
    checks = [run(["python3", "tools/validate_v1_execution.py"]),
              run(["python3", "-m", "pytest", "-q", *CONTROL_TESTS]),
              run(["python3", "-m", "pytest", "-q", *MEDIA_TESTS]),
              run(["python3", "-m", "pytest", "-q", *fast_tests]),
              run(["python3", "-m", "compileall", "-q", "skills", "tools", "tests"])]
    report = {"schema_version": 1, "versions": versions(), "checks": checks,
              "artifact": artifact(args.artifact) if args.artifact else None,
              "public_visibility_authorized": False}
    report["release_ready"] = report["versions"]["coherent"] and all(row["exit"] == 0 for row in checks) and bool(report["artifact"] and report["artifact"]["valid"])
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["release_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
