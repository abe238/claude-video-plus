"""--boundary-anchors: fade / held-frame / silence boundaries from one ffmpeg pass.

Opt-in (default path unchanged). Mirrors the --text-anchors tests: evidence latch,
shared budget, manual --timestamps precedence, fail-open.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import boundaries
from boundaries import detect_boundaries, parse_boundaries, select_boundaries

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts" / "watch.py"

CANNED = """
[Parsed_silencedetect_0 @ 0x1] silence_start: 5.01551
[Parsed_freezedetect_2 @ 0x1] lavfi.freezedetect.freeze_start: 5.533333
[Parsed_blackdetect_1 @ 0x1] black_start:5.266667 black_end:6.266667 black_duration:1
[Parsed_silencedetect_0 @ 0x1] silence_end: 8.521723 | silence_duration: 3.506213
[Parsed_freezedetect_2 @ 0x1] lavfi.freezedetect.freeze_start: 9
"""


# --- parse level -------------------------------------------------------------


def test_parse_canned_stderr():
    marks = dict((k, t) for t, k in parse_boundaries(CANNED))
    assert marks["black-end"] == pytest.approx(6.52)
    assert marks["silence-end"] == pytest.approx(8.52)
    assert [t for t, k in parse_boundaries(CANNED) if k == "freeze-start"] == [5.63, 9.1]


def test_parse_applies_offset_and_ignores_garbage():
    assert parse_boundaries("nothing here\nblack_start:x black_end:y") == []
    assert parse_boundaries("silence_end: 2.0 | silence_duration: 1", offset=10.0) == [(12.0, "silence-end")]


def test_select_dedupes_keeps_priority_and_chronological():
    marks = [(8.5, "silence-end"), (9.1, "freeze-start"), (30.0, "silence-end")]
    # 8.5 and 9.1 are within 1 s: the higher-priority freeze-start wins.
    assert select_boundaries(marks) == [(9.1, "freeze-start"), (30.0, "silence-end")]


def test_select_dedupe_does_not_drift_past_window():
    # Chain 10.0 silence, 10.8 fade, 11.6 silence: the 11.6 mark is 1.6 s from the
    # cluster's first mark, so it must start a NEW cluster (old code drifted).
    marks = [(10.0, "silence-end"), (10.8, "black-end"), (11.6, "silence-end")]
    assert select_boundaries(marks) == [(10.8, "black-end"), (11.6, "silence-end")]


def test_cap_by_priority_fades_then_cards_then_silences():
    marks = ([(float(t), "silence-end") for t in range(100, 200, 2)]
             + [(5.0, "black-end"), (50.0, "black-end"), (70.0, "freeze-start"), (80.0, "freeze-start")])
    out = boundaries.cap_by_priority(marks, 4)
    assert [k for _, k in out] == ["black-end", "black-end", "freeze-start", "freeze-start"]
    out = boundaries.cap_by_priority(marks, 6)  # 2 fades + 2 cards + 2 silences spread over the span
    silences = [t for t, k in out if k == "silence-end"]
    assert len(out) == 6 and silences == [100.0, 198.0]
    assert boundaries.cap_by_priority(marks, 1) == [(5.0, "black-end")]


def test_select_window_and_cap():
    marks = [(float(t * 10), "black-end") for t in range(1, 8)]
    assert [t for t, _ in select_boundaries(marks, lo=25, hi=55)] == [30.0, 40.0, 50.0]
    assert len(select_boundaries(marks, limit=3)) == 3
    assert select_boundaries(marks, limit=0) == []


def test_select_hard_cap_is_enforced():
    marks = [(float(t * 2), "black-end") for t in range(boundaries.MAX_BOUNDARIES + 50)]
    assert len(select_boundaries(marks, limit=10_000)) == boundaries.MAX_BOUNDARIES


# --- fail-open ---------------------------------------------------------------


def test_fail_open_no_ffmpeg(monkeypatch):
    monkeypatch.setattr(boundaries.shutil, "which", lambda _n: None)
    assert detect_boundaries("x.mp4") == ([], "ffmpeg not installed")


def test_fail_open_ffmpeg_error_and_timeout(tmp_path):
    bad = tmp_path / "not-a-video.mp4"
    bad.write_bytes(b"garbage")
    out, note = detect_boundaries(str(bad))
    assert out == [] and note


def test_fail_open_subprocess_raises(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ffmpeg", 1)
    monkeypatch.setattr(boundaries, "run_bounded", boom)
    out, note = detect_boundaries("x.mp4")
    assert out == [] and "TimeoutExpired" in note


def test_fail_open_on_timeout_rc124(monkeypatch):
    import config
    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(boundaries, "run_bounded", lambda cmd, **kw: config.run_bounded(cmd, runner=hang, **kw))
    monkeypatch.setattr(boundaries.shutil, "which", lambda _n: "/usr/bin/ffmpeg")
    out, note = detect_boundaries("x.mp4", duration=10.0)
    assert out == [] and "124" in note


# --- real ffmpeg -------------------------------------------------------------


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    p = tmp_path_factory.mktemp("bnd") / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=s=320x240:r=15:d=6",
         "-f", "lavfi", "-i", "testsrc2=s=320x240:r=15:d=3",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=15:d=3",
         "-f", "lavfi", "-i", "sine=f=440:d=12",
         "-filter_complex",
         "[0:v]fade=t=out:st=3:d=2.5[a];[1:v]fade=t=in:st=0:d=2[b];"
         "[a][b][2:v]concat=n=3:v=1:a=0[v];"
         "[3:a]volume=enable='between(t,5,8.5)':volume=0[au]",
         "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(p)],
        check=True,
    )
    return p


def test_real_clip_finds_fade_end_and_held_card(clip):
    out, note = detect_boundaries(str(clip), duration=12.0)
    assert note is None
    # fade-up out of black ends ~6.27 (+0.25), held blue card starts at 9.0 (+0.1)
    assert any(abs(t - 6.5) <= 0.5 for t, _ in out), out
    assert any(abs(t - 9.1) <= 0.5 for t, _ in out), out


def test_real_clip_silence_end_found_when_not_deduped(clip):
    # Focus on 7..12 so the silence end (8.52) is the first mark in range.
    out, _ = detect_boundaries(str(clip), start_seconds=7.0, end_seconds=8.9, duration=12.0)
    assert any(abs(t - 8.52) <= 0.5 for t, _ in out), out


def test_real_clip_focus_offset_is_absolute(clip):
    out, _ = detect_boundaries(str(clip), start_seconds=8.0, end_seconds=12.0, duration=12.0)
    assert any(abs(t - 9.1) <= 0.5 for t, _ in out), out
    assert all(t >= 8.0 for t, _ in out)


def test_video_without_audio_does_not_error(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    p = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x120:r=10:d=3",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    out, note = detect_boundaries(str(p), duration=3.0, has_audio=False)
    assert note is None and out  # the static clip is one freeze


# --- orchestration: latch, budget, precedence, fail-open ---------------------


def _resolve(found, **kw):
    import watch
    found = [m if isinstance(m, tuple) else (m, "black-end") for m in found]
    base = dict(
        active=True, video_path="v.mp4", have_video=True, lo=0.0, hi=100.0,
        max_frames=20, manual_timestamps=[], current_timestamps=[],
        detect=lambda *a, **k: (found, None),
    )
    base.update(kw)
    return watch.resolve_boundary_anchors(**base)


def test_evidence_latch():
    import watch
    assert watch.boundary_anchors_enabled("evidence", True) is False
    assert watch.boundary_anchors_enabled("balanced", True) is True
    assert watch.boundary_anchors_enabled("balanced", False) is False


def test_off_is_passthrough():
    ts, status = _resolve([5.0], active=False, current_timestamps=[3.0], manual_timestamps=[3.0])
    assert ts == [3.0] and status is None


def test_adds_bounded_and_keeps_manual():
    ts, status = _resolve([10.0, 20.0, 30.0], manual_timestamps=[50.0], current_timestamps=[50.0])
    assert status == "added:3" and {10.0, 20.0, 30.0, 50.0} == set(ts)


def test_cap_30_percent_of_frame_budget():
    found = [float(i * 5) for i in range(1, 15)]
    ts, _ = _resolve(found, max_frames=20)  # floor(0.3*20)=6
    assert len(ts) == 6


def test_manual_precedence_and_budget_spent():
    manual = [float(i) for i in range(200, 218)]  # 18 manual, cap 20 -> room 2
    ts, status = _resolve([1.0, 11.0, 21.0, 31.0], manual_timestamps=manual, current_timestamps=manual)
    assert set(manual) <= set(ts) and len(set(ts) - set(manual)) <= 2
    manual20 = [float(i) for i in range(20)]
    ts, status = _resolve([50.0], manual_timestamps=manual20, current_timestamps=manual20)
    assert status == "budget-spent" and ts == manual20


def test_shares_budget_with_text_anchors_not_doubles():
    # cap 20 -> shared limit 6. Text anchors already used 4 -> boundaries get 2.
    text = [1.0, 2.0, 3.0, 4.0]
    ts, status = _resolve([10.0, 20.0, 30.0, 40.0], current_timestamps=text)
    assert len(set(ts) - set(text)) == 2
    # text anchors used the whole limit -> nothing left
    text6 = [float(i) for i in range(1, 7)]
    ts, status = _resolve([10.0], current_timestamps=text6)
    assert status == "budget-spent" and ts == text6


def test_skips_boundary_already_covered_by_a_cue():
    ts, status = _resolve([10.2], current_timestamps=[10.0], manual_timestamps=[10.0])
    assert status == "none-found" and ts == [10.0]


def test_budget_cap_is_priority_not_even_sample():
    # 20 silences + 1 fade + 1 card, limit 3: both structural marks must survive.
    found = [(float(t), "silence-end") for t in range(100, 120)] + [(5.0, "black-end"), (60.0, "freeze-start")]
    ts, status = _resolve(found, max_frames=10, hi=1000.0)  # limit floor(0.3*10)=3
    assert 5.0 in ts and 60.0 in ts and status == "added:3"
    ts, _ = _resolve(found, max_frames=7)  # limit 2: fade + card only
    assert sorted(ts) == [5.0, 60.0]


def test_audio_only_source_skips_boundary_anchors():
    ts, status = _resolve([(5.0, "silence-end")], has_video_stream=False, current_timestamps=[3.0])
    assert ts == [3.0] and status == "audio-only"


def test_detector_note_or_exception_fails_open():
    ts, status = _resolve([], current_timestamps=[3.0], detect=lambda *a, **k: ([], "ffmpeg exited 1"))
    assert ts == [3.0] and status.startswith("error:")

    def boom(*a, **k):
        raise RuntimeError("x")
    ts, status = _resolve([], current_timestamps=[3.0], detect=boom)
    assert ts == [3.0] and status.startswith("error:")


def test_no_video_fails_open():
    ts, status = _resolve([5.0], have_video=False, current_timestamps=[3.0])
    assert ts == [3.0] and status == "no-video"


def test_flag_is_really_registered_and_default_off():
    out = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "--boundary-anchors" in out.stdout


def test_end_to_end_flag_adds_cue_frames(clip, tmp_path):
    base = [sys.executable, str(SCRIPT), str(clip), "--detail", "balanced"]
    off = subprocess.run(base + ["--out-dir", str(tmp_path / "off")], capture_output=True, text=True, timeout=120)
    on = subprocess.run(base + ["--boundary-anchors", "--out-dir", str(tmp_path / "on")],
                        capture_output=True, text=True, timeout=120)
    assert off.returncode == 0 and on.returncode == 0
    assert "Cue frames" not in off.stdout
    assert "Cue frames" in on.stdout and "(boundary" in on.stdout
    assert "at transcript timestamps" not in on.stdout
    assert "boundary anchor(s) added" in on.stderr


def test_extract_at_timestamps_reason_param(clip, tmp_path):
    import frames
    out, _ = frames.extract_at_timestamps(str(clip), tmp_path / "a", [1.0, 2.0])
    assert {f["reason"] for f in out} == {"transcript-cue"}
    out, _ = frames.extract_at_timestamps(str(clip), tmp_path / "b", [1.0, 2.0], reason="boundary")
    assert {f["reason"] for f in out} == {"boundary"}
    out, _ = frames.extract_at_timestamps(str(clip), tmp_path / "c", [1.0, 2.0],
                                          reason=lambda t: "boundary" if t == 2.0 else "transcript-cue")
    assert [f["reason"] for f in out] == ["transcript-cue", "boundary"]
