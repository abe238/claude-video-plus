#!/usr/bin/env python3
"""Build a deterministic, runtime-only watch.skill ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


MAX_BYTES = 250 * 1024
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
RUNTIME_SCRIPTS = (
    "acquisition.py", "config.py", "download.py", "evidence.py", "frames.py",
    "lifecycle.py", "portable.py", "question.py", "retrieval.py", "semantic.py",
    "setup.py", "state.py", "transcribe.py", "transcription.py",
    "transcription_adapters.py", "transcription_chunks.py", "vision.py", "watch.py",
    "whisper.py",
)


def runtime_files(skill_dir: Path) -> list[Path]:
    files = [skill_dir / "SKILL.md"]
    files.extend(skill_dir / "scripts" / name for name in RUNTIME_SCRIPTS)
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise ValueError(f"missing runtime file(s): {', '.join(missing)}")
    unexpected = sorted(
        path.name for path in (skill_dir / "scripts").glob("*.py")
        if path.name not in RUNTIME_SCRIPTS
    )
    if unexpected:
        raise ValueError(f"unexpected runtime Python file(s): {', '.join(unexpected)}")
    return files


def build(skill_dir: Path, output: Path) -> dict:
    skill_dir = skill_dir.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = runtime_files(skill_dir)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            relative = source.relative_to(skill_dir).as_posix()
            info = zipfile.ZipInfo(f"watch/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)
    size = output.stat().st_size
    if size >= MAX_BYTES:
        output.unlink(missing_ok=True)
        raise ValueError(f"bundle is {size} bytes; limit is {MAX_BYTES - 1}")
    names = [f"watch/{path.relative_to(skill_dir).as_posix()}" for path in files]
    return {
        "path": str(output),
        "files": names,
        "file_count": len(names),
        "bytes": size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    receipt = build(args.skill_dir, args.output)
    print(json.dumps(receipt, sort_keys=True) if args.json else f"built {receipt['path']} ({receipt['file_count']} files, {receipt['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
