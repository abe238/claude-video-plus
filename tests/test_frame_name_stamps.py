"""v1.5.4 B3: timestamps in main-pass frame filenames (bugsmithd fork audit).

One post-selection chokepoint (frames.stamp_frame_names) invoked at every
engine exit, after dedup and even-sampling. Collision and rename failure are
fail-open: the dict path updates only after a successful rename. Cue frames
(cue_*/t02m30s.jpg, evidence mode) are untouched.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import frames as frames_mod
from frames import extract_keyframes, extract_scene_or_uniform, stamp_frame_names


def _fake_frames(tmp_path: Path, specs) -> list[dict]:
    out = []
    for i, ts in enumerate(specs):
        path = tmp_path / f"frame_{i:04d}.jpg"
        path.write_bytes(b"jpg")
        out.append({"index": i, "timestamp_seconds": ts, "path": str(path), "reason": "test"})
    return out


def test_stamp_format_sub_hour_and_rollover(tmp_path):
    stamped = stamp_frame_names(_fake_frames(tmp_path, [252.4, 3661.0, 0.0]))
    names = [Path(f["path"]).name for f in stamped]
    assert names[0] == "frame_0000_t04m12s.jpg"   # nearest-second, like format_time
    assert names[1] == "frame_0001_t1h01m01s.jpg"  # hour rollover, colon-free
    assert names[2] == "frame_0002_t00m00s.jpg"
    for f in stamped:
        assert Path(f["path"]).exists()  # dict path == on-disk path
        assert ":" not in Path(f["path"]).name  # Windows-safe


def test_stamp_rounds_like_format_time(tmp_path):
    [stamped] = stamp_frame_names(_fake_frames(tmp_path, [59.6]))
    assert Path(stamped["path"]).name == "frame_0000_t01m00s.jpg"  # rounds, not truncates


def test_collision_keeps_original_path(tmp_path):
    frames = _fake_frames(tmp_path, [5.0])
    (tmp_path / "frame_0000_t00m05s.jpg").write_bytes(b"stale")  # squatter
    [stamped] = stamp_frame_names(frames)
    assert Path(stamped["path"]).name == "frame_0000.jpg"  # never overwrite
    assert Path(stamped["path"]).exists()
    assert (tmp_path / "frame_0000_t00m05s.jpg").read_bytes() == b"stale"


def test_rename_failure_keeps_original_path(tmp_path, monkeypatch):
    import os as _os

    frames = _fake_frames(tmp_path, [5.0, 6.0])
    original = _os.link

    def failing_link(src, dst, **kwargs):
        if Path(src).name == "frame_0000.jpg":
            raise OSError("locked")
        return original(src, dst, **kwargs)

    monkeypatch.setattr(_os, "link", failing_link)
    stamped = stamp_frame_names(frames)
    # Partial failure: frame 0 keeps its original (existing) path, frame 1 stamps.
    assert Path(stamped[0]["path"]).name == "frame_0000.jpg"
    assert Path(stamped[0]["path"]).exists()
    assert Path(stamped[1]["path"]).name == "frame_0001_t00m06s.jpg"
    assert Path(stamped[1]["path"]).exists()


def test_idempotent_on_already_stamped_names(tmp_path):
    once = stamp_frame_names(_fake_frames(tmp_path, [5.0]))
    twice = stamp_frame_names(once)
    assert twice == once
    assert Path(twice[0]["path"]).exists()


def test_missing_timestamp_stamps_zero(tmp_path):
    path = tmp_path / "frame_0000.jpg"
    path.write_bytes(b"jpg")
    [stamped] = stamp_frame_names([{"path": str(path)}])
    assert Path(stamped["path"]).name == "frame_0000_t00m00s.jpg"


# --- every engine exit stamps (real ffmpeg clips) --------------------------


def _assert_all_stamped(frames: list[dict]):
    assert frames
    for frame in frames:
        name = Path(frame["path"]).name
        assert re.search(r"_t\d+(?:h\d{2}m|m)\d{2}s\.jpg$", name), name
        assert Path(frame["path"]).exists()


def test_keyframe_engine_stamps(cut_clip, tmp_path):
    frames, meta = extract_keyframes(str(cut_clip), tmp_path / "kf", max_frames=6)
    assert meta["engine"] in ("keyframe", "uniform")
    _assert_all_stamped(frames)


def test_scene_engine_stamps(cut_clip, tmp_path):
    frames, meta = extract_scene_or_uniform(
        str(cut_clip), tmp_path / "scene", fps=1.0, target_frames=6, max_frames=6
    )
    _assert_all_stamped(frames)


def test_uniform_fallback_stamps(static_clip, tmp_path):
    frames, meta = extract_scene_or_uniform(
        str(static_clip), tmp_path / "uni", fps=1.0, target_frames=4, max_frames=4
    )
    assert meta["fallback"] is True
    _assert_all_stamped(frames)


def test_no_dedup_path_stamps(cut_clip, tmp_path):
    frames, _meta = extract_scene_or_uniform(
        str(cut_clip), tmp_path / "nd", fps=1.0, target_frames=6, max_frames=6, dedup=False
    )
    _assert_all_stamped(frames)


def test_glob_consumers_still_match_stamped_names(cut_clip, tmp_path):
    # The cleanup/discovery globs are all `frame_*.jpg`: a second extraction
    # into the SAME directory must clean the previous stamped output or the
    # frame↔timestamp pairing corrupts.
    out = tmp_path / "re"
    first, _ = extract_keyframes(str(cut_clip), out, max_frames=4)
    second, _ = extract_keyframes(str(cut_clip), out, max_frames=4)
    on_disk = sorted(p.name for p in out.glob("frame_*.jpg"))
    reported = sorted(Path(f["path"]).name for f in second)
    assert on_disk == reported  # nothing stale survived the re-extraction


def test_conformance_canonicalization_strips_only_the_stamp():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from control_conformance import canonicalize_frame_names

    assert canonicalize_frame_names("frame_0007_t04m12s.jpg") == "frame_0007.jpg"
    assert canonicalize_frame_names("frame_0007_t1h04m12s.jpg") == "frame_0007.jpg"
    assert canonicalize_frame_names("cue_0001.jpg") == "cue_0001.jpg"
    assert canonicalize_frame_names("t02m30s.jpg") == "t02m30s.jpg"  # evidence cue frames
    assert canonicalize_frame_names("frame_0007.jpg") == "frame_0007.jpg"


def test_standalone_cli_stamps_frames(cut_clip, tmp_path):
    import json
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts" / "frames.py"
    for extra in ([], ["--no-dedup"]):
        out_dir = tmp_path / ("cli" + ("nd" if extra else ""))
        result = subprocess.run(
            [sys.executable, str(script), str(cut_clip), str(out_dir), "--max-frames", "4", *extra],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        _assert_all_stamped(payload["frames"])


def test_conformance_leaves_spoken_stamp_names_alone():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from control_conformance import canonicalize_report_frame_lines

    report = (
        "- `<TMP_PATH>/frames/frame_0007_t04m12s.jpg` (t=252.4, reason=scene)\n"
        "[04:10] and then he said open frame_0007_t04m12s.jpg on your machine\n"
    )
    canonical = canonicalize_report_frame_lines(report)
    lines = canonical.splitlines()
    assert "frame_0007.jpg" in lines[0]            # path line: canonicalized
    assert "frame_0007_t04m12s.jpg" in lines[1]    # spoken content: untouched


def test_watch_report_paths_match_disk_end_to_end(cut_clip, monkeypatch, capsys):
    """B3 acceptance: every frame path the REPORT prints exists on disk with
    its stamped name (the dict-update-after-rename contract, observed at the
    real output boundary)."""
    import sys as _sys

    import watch

    monkeypatch.setattr(
        _sys, "argv", ["watch.py", str(cut_clip), "--no-whisper", "--detail", "efficient"]
    )
    rc = watch.main()
    out = capsys.readouterr().out
    assert rc == 0
    reported = re.findall(r"`([^`]*frames[\\/]frame_[^`]+\.jpg)`", out)
    assert reported, "report printed no frame paths"
    for path in reported:
        assert re.search(r"_t\d+(?:h\d{2}m|m)\d{2}s\.jpg$", path), path
        assert Path(path).exists(), path


def test_dangling_symlink_destination_is_never_clobbered(tmp_path):
    import os
    import sys

    if sys.platform == "win32":
        pytest.skip("symlink creation needs privilege on Windows")
    frames = _fake_frames(tmp_path, [5.0])
    dangling = tmp_path / "frame_0000_t00m05s.jpg"
    os.symlink(tmp_path / "nonexistent-target", dangling)
    assert not dangling.exists()  # exists() lies about dangling links...
    [stamped] = stamp_frame_names(frames)
    # ...but os.link refuses ANY existing directory entry: fail-open.
    assert Path(stamped["path"]).name == "frame_0000.jpg"
    assert Path(stamped["path"]).is_file()
    assert dangling.is_symlink()  # the squatter is untouched


def test_conformance_parses_windows_style_frame_lines():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from control_conformance import FRAME_LINE_RE, canonicalize_report_frame_lines

    line = r"- `<TMP_PATH>\frames\frame_0007_t04m12s.jpg` (t=252.4, reason=scene)" + "\n"
    assert FRAME_LINE_RE.findall(line) == [("frame_0007_t04m12s.jpg", "252.4", "scene")]
    assert "frame_0007.jpg" in canonicalize_report_frame_lines(line)
