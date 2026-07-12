#!/usr/bin/env python3
"""Cross-host diagnostics and explicit cleanup for installed /watch state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from pathlib import Path


CONFIG_ROOT = Path.home() / ".config" / "watch"
CACHE_ROOT = Path.home() / ".cache" / "watch"
HOST_ROOTS = {
    "codex": Path.home() / ".codex" / "skills" / "watch",
    "claude": Path.home() / ".claude" / "skills" / "watch",
    "agents": Path.home() / ".agents" / "skills" / "watch",
    "cursor": Path.home() / ".cursor" / "skills" / "watch",
}


def inspect() -> dict:
    installs = {}
    for host, path in HOST_ROOTS.items():
        installs[host] = {"path": str(path), "exists": path.exists(), "symlink": path.is_symlink(),
                          "skill": (path / "SKILL.md").is_file(), "runtime": (path / "scripts/watch.py").is_file()}
    return {"schema_version": 1, "installs": installs,
            "config": {"path": str(CONFIG_ROOT), "exists": CONFIG_ROOT.exists()},
            "cache": {"path": str(CACHE_ROOT), "exists": CACHE_ROOT.exists()},
            "tools": {name: shutil.which(name) for name in ("python3", "python", "ffmpeg", "ffprobe", "yt-dlp")}}


def _safe_root(path: Path) -> Path:
    path = path.expanduser()
    allowed = {CONFIG_ROOT, CACHE_ROOT, *HOST_ROOTS.values()}
    if path not in allowed or path == Path.home():
        raise ValueError("refusing cleanup outside known watch roots")
    return path


def remove(path: Path) -> bool:
    path = _safe_root(path)
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)
    return True


def secure_config() -> None:
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CONFIG_ROOT, stat.S_IRWXU)
    env = CONFIG_ROOT / ".env"
    if env.exists():
        os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--purge-cache", action="store_true")
    parser.add_argument("--purge-config", action="store_true")
    parser.add_argument("--uninstall-host", choices=sorted(HOST_ROOTS))
    args = parser.parse_args()
    actions = []
    if args.purge_cache:
        actions.append({"purge_cache": remove(CACHE_ROOT)})
    if args.purge_config:
        actions.append({"purge_config": remove(CONFIG_ROOT)})
    if args.uninstall_host:
        actions.append({"uninstall_host": args.uninstall_host,
                        "removed": remove(HOST_ROOTS[args.uninstall_host])})
    result = inspect()
    result["actions"] = actions
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
