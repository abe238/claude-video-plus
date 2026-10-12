"""Every child process in skills/watch/scripts is bounded, and a hang is a handled failure."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import acquisition  # noqa: E402
import config  # noqa: E402
import download  # noqa: E402
import frames  # noqa: E402

_SPAWNERS = {"run", "Popen", "check_output", "call", "check_call"}


def unbounded_calls(source: str) -> list[int]:
    """Line numbers of subprocess spawns (or a bare `runner(...)`) without a timeout= keyword."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        spawns = (isinstance(f, ast.Attribute) and f.attr in _SPAWNERS
                  and isinstance(f.value, ast.Name) and f.value.id in ("subprocess", "sp"))
        spawns = spawns or (isinstance(f, ast.Name) and f.id in _SPAWNERS | {"runner"})
        if spawns and not any(k.arg == "timeout" for k in node.keywords):
            bad.append(node.lineno)
    return bad


def test_audit_positive_control():
    # The audit must catch a call without timeout, or "clean" below proves nothing.
    assert unbounded_calls("import subprocess\nsubprocess.run(['x'])\n") == [2]
    assert unbounded_calls("subprocess.Popen(['x'])\nrunner(cmd)\n") == [1, 2]
    assert unbounded_calls("subprocess.run(['x'], timeout=5)\nrunner(c, timeout=1)\n") == []


def test_every_child_process_has_a_timeout():
    files = sorted(SCRIPTS.glob("*.py"))
    assert len(files) > 10  # the glob found the scripts
    offenders = {f.name: unbounded_calls(f.read_text(encoding="utf-8")) for f in files}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_run_bounded_maps_timeout_to_nonzero_exit():
    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    text = config.run_bounded(["x"], timeout=3, runner=hang, capture_output=True, text=True)
    assert text.returncode == 124 and "timed out" in text.stderr and text.stdout == ""
    raw = config.run_bounded(["x"], timeout=3, runner=hang, capture_output=True)
    assert raw.returncode == 124 and raw.stdout == b""


def test_ffmpeg_timeout_scales_with_duration():
    assert config.ffmpeg_timeout(None) == 3600
    assert config.ffmpeg_timeout(60) == 600
    assert config.ffmpeg_timeout(7200) == 21600


@pytest.fixture
def hung_children(monkeypatch):
    def hang(cmd, **kw):
        assert kw.get("timeout"), "child spawned without a timeout"
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)


def test_frames_probe_hang_takes_existing_probe_failure_path(hung_children, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:  # the same exit an unusable ffprobe/ffmpeg produces
        frames.get_metadata(str(video))
    assert "timed out" in str(exc.value)


def test_frames_thumbnail_hang_fails_open(hung_children, tmp_path):
    paths = [tmp_path / "frame_0001.jpg", tmp_path / "frame_0002.jpg"]
    assert frames._thumb_frames(paths) == []  # dedup skipped, extraction not broken


def test_acquisition_hang_is_a_classified_retryable_failure(hung_children, tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "ytdlp_cmd", lambda: ("yt-dlp",))
    result = acquisition.acquire_url(
        "https://example.com/video",
        tmp_path,
        runner=subprocess.run,
        pick_media=download._pick_video,
        pick_subtitles=download._subtitle_candidates,
        read_metadata=download._read_info,
    )
    assert result.state == "fatal"
    assert result.attempts[0].failure_class == acquisition.FailureClass.NETWORK_TIMEOUT.value
