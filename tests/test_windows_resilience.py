"""WDAC/Smart-App-Control resilience: blocked-binary fallbacks.

Prior art: vgrosetti-maker/claude-video (reimplemented). The ffprobe→ffmpeg
banner fallbacks are exercised LIVE against real ffmpeg output; the yt-dlp
probe branches are exercised with fakes (a blocked exe cannot be reproduced
on macOS/Linux).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import acquisition
import frames
import whisper


@pytest.fixture(autouse=True)
def _reset_ytdlp_probe():
    acquisition.ytdlp_cmd.cache_clear()
    yield
    acquisition.ytdlp_cmd.cache_clear()


def _no_ffprobe(monkeypatch, module):
    real_which = module.shutil.which
    monkeypatch.setattr(
        module.shutil, "which",
        lambda name: None if name == "ffprobe" else real_which(name),
    )


def test_get_metadata_falls_back_to_ffmpeg_banner(cut_clip: Path, monkeypatch):
    baseline = frames.get_metadata(str(cut_clip))
    _no_ffprobe(monkeypatch, frames)
    fallback = frames.get_metadata(str(cut_clip))
    assert fallback["width"] == baseline["width"]
    assert fallback["height"] == baseline["height"]
    assert fallback["has_audio"] == baseline["has_audio"]
    assert abs(fallback["duration_seconds"] - baseline["duration_seconds"]) < 0.5
    assert fallback["size_bytes"] > 0


def test_get_metadata_falls_back_when_ffprobe_errors(cut_clip: Path, monkeypatch):
    real_run = frames.subprocess.run

    def failing_ffprobe(cmd, **kwargs):
        if cmd and cmd[0] == "ffprobe":
            raise OSError(4551, "blocked by policy")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(frames.subprocess, "run", failing_ffprobe)
    meta = frames.get_metadata(str(cut_clip))
    assert meta["duration_seconds"] > 0


def test_audio_duration_falls_back_to_ffmpeg_banner(tmp_path: Path, monkeypatch):
    wav = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", str(wav)],
        check=True,
    )
    baseline = whisper.audio_duration(wav)
    _no_ffprobe(monkeypatch, whisper)
    assert abs(whisper.audio_duration(wav) - baseline) < 0.5
    assert baseline > 2.5


def test_ytdlp_cmd_prefers_working_exe(monkeypatch):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: "/fake/yt-dlp")
    monkeypatch.setattr(
        acquisition.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    assert acquisition.ytdlp_cmd() == ("yt-dlp",)


def test_ytdlp_cmd_blocked_exe_falls_back_to_module(monkeypatch):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: "/fake/yt-dlp")

    def run(cmd, **kwargs):
        if cmd[0] == "/fake/yt-dlp":
            raise OSError(4551, "blocked by policy")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(acquisition.subprocess, "run", run)
    assert acquisition.ytdlp_cmd() == (acquisition.sys.executable, "-m", "yt_dlp")


def test_ytdlp_cmd_fails_open_when_nothing_usable(monkeypatch):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: None)

    def run(cmd, **kwargs):
        raise OSError("no such module either")

    monkeypatch.setattr(acquisition.subprocess, "run", run)
    assert acquisition.ytdlp_cmd() == ("yt-dlp",)


def test_build_yt_dlp_command_uses_probed_invocation(monkeypatch):
    monkeypatch.setattr(acquisition, "ytdlp_cmd", lambda: ("python", "-m", "yt_dlp"))
    cmd = acquisition.build_yt_dlp_command(
        "https://x/v", "/tmp/video.%(ext)s",
        audio_only=False, captions_only=True,
        languages=("en",), cookie_spec=None,
    )
    assert cmd[:3] == ["python", "-m", "yt_dlp"]
    assert "--skip-download" in cmd
