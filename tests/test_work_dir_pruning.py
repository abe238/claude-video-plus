"""Stale work-dir housekeeping.

Prior art: dluxcru/claude-video (reimplemented with a 24h window so a dir kept
for follow-up questions — SKILL.md Step 5 — is never deleted out from under it).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import watch


def _aged(path: Path, age_seconds: float) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def test_prunes_only_dirs_past_the_window(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watch.tempfile, "gettempdir", lambda: str(tmp_path))
    stale = tmp_path / "watch-stale"
    stale.mkdir()
    # Write payload BEFORE ageing: creating a file bumps the parent's mtime,
    # which is the intended behaviour (a dir being written to reads as in-use).
    (stale / "video.mp4").write_bytes(b"payload")
    _aged(stale, 25 * 3600)
    fresh = _aged(tmp_path / "watch-fresh", 60)
    recent = _aged(tmp_path / "watch-recent", 23 * 3600)  # inside follow-up window

    assert watch._prune_stale_work_dirs() == 1
    assert not stale.exists()
    assert fresh.exists()
    assert recent.exists()


def test_leaves_unrelated_entries_alone(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watch.tempfile, "gettempdir", lambda: str(tmp_path))
    other = _aged(tmp_path / "not-watch", 99 * 3600)
    stray_file = tmp_path / "watch-file.log"
    stray_file.write_text("keep me", encoding="utf-8")
    old = time.time() - 99 * 3600
    os.utime(stray_file, (old, old))

    assert watch._prune_stale_work_dirs() == 0
    assert other.exists()
    assert stray_file.exists()


def test_symlink_is_never_followed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watch.tempfile, "gettempdir", lambda: str(tmp_path))
    victim = tmp_path / "precious"
    victim.mkdir()
    (victim / "keep.txt").write_text("data", encoding="utf-8")
    link = tmp_path / "watch-link"
    link.symlink_to(victim, target_is_directory=True)
    old = time.time() - 99 * 3600
    os.utime(link, (old, old), follow_symlinks=False)

    assert watch._prune_stale_work_dirs() == 0
    assert (victim / "keep.txt").exists()


def test_missing_tempdir_is_not_fatal(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watch.tempfile, "gettempdir", lambda: str(tmp_path / "gone"))
    assert watch._prune_stale_work_dirs() == 0
