"""Three community-found defects, each reproduced before it was fixed.

Sources (upstream PRs against the abandoned bradautomates/claude-video; ideas
only, reimplemented here):
  * OpenClawLinda #225 — a VTT cue whose first line is a lone space is dropped.
  * OpenClawLinda #226 — uniform extract() samples the HEAD of the range when
    fps * duration exceeds the frame cap, and reports it as a full-range pass.
  * sainbayare-net #97 — `--detail efficient` raises instead of falling back
    when a range contains no keyframes.

Every test here went red against the pre-fix tree; the failure each one
reproduces is named in its docstring so a future edit cannot quietly weaken it.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "watch" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import frames as F  # noqa: E402
import transcribe as T  # noqa: E402

ffmpeg_only = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


# --- OpenClawLinda #225: lone-space cue terminator ---------------------------

def test_lone_space_first_line_does_not_drop_the_cue(tmp_path: Path):
    """RED before the fix: `while lines[i].strip()` treats a whitespace-only
    line as the cue terminator, so a cue whose first line is a lone space (a
    placeholder YouTube emits) parsed to ZERO segments and its text vanished
    from the transcript with no error. Exit-0 data loss."""
    vtt = tmp_path / "lonespace.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        " \n"                                  # lone-space placeholder
        "opening line that matters\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "second line\n\n",
        encoding="utf-8",
    )
    segs = T.parse_subtitle(vtt)
    texts = " | ".join(s["text"] for s in segs)
    assert len(segs) == 2, f"expected both cues, got {len(segs)}: {texts}"
    assert "opening line that matters" in texts


def test_a_truly_empty_line_still_ends_the_cue(tmp_path: Path):
    """Guard the other direction: the fix must not merge adjacent cues."""
    vtt = tmp_path / "normal.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\nalpha\n\n"
        "00:00:02.000 --> 00:00:04.000\nbravo\n\n",
        encoding="utf-8",
    )
    segs = T.parse_subtitle(vtt)
    assert [s["text"] for s in segs] == ["alpha", "bravo"]


# --- OpenClawLinda #226: uniform head truncation -----------------------------

@ffmpeg_only
def test_uniform_extract_spreads_across_the_range_when_fps_exceeds_cap(tmp_path: Path):
    """RED before the fix: `-vf fps=N` samples evenly across the whole input but
    `-frames:v CAP` just STOPS after CAP outputs, so whenever fps*duration >
    cap the result is the first CAP samples — the head — while the report calls
    it a full-range pass. Measured on the pre-fix tree with a 120s clip at
    fps=0.5 capped to 20: last frame at 38.0s of 120s."""
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=120:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    # fps*duration = 60 wanted, cap 20 → the two disagree, which is the bug's shape.
    out = F.extract(str(clip), tmp_path / "f", fps=0.5, resolution=256, max_frames=20)
    assert len(out) <= 20
    last = out[-1]["timestamp_seconds"]
    # Spread means the tail is sampled. Pre-fix this was ~38s.
    assert last > 90, f"frames truncated to the head: last={last}s of 120s"
    # Timestamps must describe the frames actually taken, in order.
    ts = [f["timestamp_seconds"] for f in out]
    assert ts == sorted(ts)


@ffmpeg_only
def test_uniform_extract_unchanged_when_fps_and_cap_agree(tmp_path: Path):
    """The auto path derives fps FROM the cap, so fps*duration never exceeds it.
    That case must keep its exact previous spacing — the fix is a no-op there."""
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=20:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    out = F.extract(str(clip), tmp_path / "f", fps=1.0, resolution=256, max_frames=100)
    ts = [f["timestamp_seconds"] for f in out]
    assert len(ts) >= 15
    # 1 fps requested and not capped → consecutive stamps one second apart.
    gaps = [round(b - a, 2) for a, b in zip(ts, ts[1:])]
    assert all(abs(g - 1.0) < 0.01 for g in gaps), gaps


# --- sainbayare-net #97: keyframe-less range ---------------------------------

@ffmpeg_only
def test_efficient_detail_falls_back_when_range_has_no_keyframes(tmp_path: Path):
    """A short --start/--end window can land between two keyframes. On some
    ffmpeg builds (reported: 8.1.1 on Windows 11) `-skip_frame nokey` then
    selects nothing and ffmpeg FAILS at mjpeg encoder init rather than exiting
    0 empty — which made the `len(candidates) < KEYFRAME_MIN` uniform fallback
    twelve lines below unreachable in exactly the case it exists for.

    This ffmpeg (macOS) exits 0 for that input, so the assertion below passes
    both before and after on this platform; the fix is what makes it hold on a
    build that exits non-zero. Kept as the regression anchor for the behaviour
    either way: a keyframe-less range must degrade, never raise."""
    clip = tmp_path / "gop.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=60:rate=25",
         "-c:v", "libx264", "-g", "500", "-keyint_min", "500",
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    out, meta = F.extract_keyframes(str(clip), tmp_path / "f", max_frames=50,
                                    start_seconds=12.0, end_seconds=18.0)
    assert meta["engine"] == "uniform" and meta["fallback"] is True
    assert len(out) > 0


@ffmpeg_only
def test_keyframe_extraction_still_raises_when_frames_were_produced(tmp_path: Path, monkeypatch):
    """The fix must not swallow a genuine mid-run failure: a non-zero exit that
    DID write frames still raises."""
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=6:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    real_run = subprocess.run

    def fail_but_emit(cmd, *a, **kw):
        result = real_run(cmd, *a, **kw)
        # Same outputs, but claim failure — the "partial decode" shape.
        return subprocess.CompletedProcess(cmd, 1, getattr(result, "stdout", ""),
                                           getattr(result, "stderr", ""))
    monkeypatch.setattr(F.subprocess, "run", fail_but_emit)
    with pytest.raises(SystemExit):
        F.extract_keyframes(str(clip), tmp_path / "f", max_frames=50)


# --- Jordan-Zhu #210: coverage is structural, pin it -------------------------

@ffmpeg_only
def test_scene_selection_covers_the_range_not_just_a_corner(tmp_path: Path):
    """#210 reported 23 scene candidates clearing the count floor while 15 sat
    inside 7 seconds, leaving a 3m25s hole. Our floor-interval injection plus
    _gap_fill spread candidates by construction, so that shape cannot occur
    here — this pins that property so a future selection edit cannot silently
    reintroduce it."""
    clip = tmp_path / "sparse.mp4"
    # Activity at the start, then a long static tail: the clustering shape.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=90:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    out, meta = F.extract_scene_or_uniform(str(clip), tmp_path / "f", fps=1.0,
                                           target_frames=40, max_frames=40, dedup=False)
    ts = sorted(f["timestamp_seconds"] for f in out)
    assert len(ts) >= 4, meta
    span = ts[-1] - ts[0]
    worst = max((b - a) for a, b in zip(ts, ts[1:]))
    even = span / (len(ts) - 1) if len(ts) > 1 else span
    # No hole more than 4x the even spacing — the #210 ratio.
    assert worst <= max(even * 4, 1.0), f"gap {worst:.1f}s vs even {even:.1f}s (engine={meta['engine']})"


# --- dsp407 #224 (keyframe half): counts must reconcile ----------------------

@ffmpeg_only
def test_keyframe_fallback_counts_reconcile(tmp_path: Path):
    """RED before the fix: the keyframe→uniform fallback reported the count of
    the DISCARDED keyframes (they are unlinked just above), printing e.g.
    "12 selected from 1 candidates". v1.5.12 fixed the identical bug on the
    SCENE fallback and missed this path. Surfaced by running the real command,
    not by a unit test."""
    clip = tmp_path / "gop.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=45:rate=15",
         "-c:v", "libx264", "-g", "500", "-keyint_min", "500",
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    out, meta = F.extract_keyframes(str(clip), tmp_path / "f", max_frames=12,
                                    start_seconds=12.0, end_seconds=18.0)
    assert meta["fallback"] is True and meta["engine"] == "uniform"
    assert meta["selected_count"] == len(out)
    assert meta["candidate_count"] >= meta["selected_count"], meta
    assert meta["candidate_count"] - meta["deduped_count"] == meta["selected_count"], meta


# --- Codex adversarial review of this change set (2026-09-21) ---------------

def test_whitespace_only_srt_separator_does_not_merge_cues(tmp_path: Path):
    """REGRESSION I INTRODUCED, caught by review: reading through every
    whitespace-only line fixed the VTT placeholder but made a whitespace-
    polluted SRT separator swallow the next cue's index, timestamp and speaker.
    Both shapes must now hold at once."""
    srt = tmp_path / "polluted.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nalpha\n"
        " \n"                                        # separator with a stray space
        "2\n00:00:01,000 --> 00:00:02,000\n<v Bob>bravo</v>\n\n",
        encoding="utf-8",
    )
    segs = T.parse_subtitle(srt)
    assert len(segs) == 2, [s["text"] for s in segs]
    assert segs[0]["text"] == "alpha"
    assert segs[1]["start"] == 1.0, "second cue lost its own timestamp"
    assert "bravo" in segs[1]["text"]


def test_cue_with_only_whitespace_body_does_not_run_into_the_next(tmp_path: Path):
    """The placeholder-skip must not consume the following cue when a cue's
    body is whitespace all the way down: a timestamp line always terminates."""
    vtt = tmp_path / "empty_body.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        " \n"
        "00:00:01.000 --> 00:00:02.000\nreal text\n\n",
        encoding="utf-8",
    )
    segs = T.parse_subtitle(vtt)
    assert any(s["text"] == "real text" and s["start"] == 1.0 for s in segs), segs


@ffmpeg_only
def test_auto_path_fractional_duration_is_untouched(tmp_path: Path):
    """The no-op claim has to hold for the REAL auto values, not a contrived
    pair: auto_fps_focus(5.6, 100) -> (2.0, 11) and 2.0*5.6 = 11.2 would have
    tripped a raw `>` comparison and shifted every timestamp."""
    clip = tmp_path / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:duration=5.6:rate=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    for fn in (F.auto_fps, F.auto_fps_focus):
        fps, target = fn(5.6, max_frames=100)
        out = F.extract(str(clip), tmp_path / f"f_{fn.__name__}", fps=fps,
                        resolution=256, max_frames=target)
        ts = [f["timestamp_seconds"] for f in out]
        if len(ts) > 1:
            gaps = [round(b - a, 3) for a, b in zip(ts, ts[1:])]
            expected = round(1.0 / fps, 3)
            assert all(abs(g - expected) < 0.01 for g in gaps), (fn.__name__, fps, target, gaps)


def test_keyframe_fallback_is_reached_when_ffmpeg_exits_nonzero_with_no_frames(tmp_path: Path, monkeypatch):
    """Deterministic pin for fix 3, independent of platform. The macOS probe
    exits 0 for a keyframe-less range, so the earlier test passed with the fix
    reverted; this one forces the reported Windows shape (non-zero exit, zero
    files) and asserts we degrade instead of raising."""
    calls = {"n": 0}
    real_run = subprocess.run

    def keyframe_pass_fails(cmd, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:                      # the -skip_frame nokey pass
            return subprocess.CompletedProcess(cmd, 1, "", "No filtered frames for output stream")
        return real_run(cmd, *a, **kw)           # the uniform fallback runs for real

    clip = tmp_path / "clip.mp4"
    real_run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
              "-i", "testsrc=size=320x240:duration=8:rate=10",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    monkeypatch.setattr(F.subprocess, "run", keyframe_pass_fails)
    out, meta = F.extract_keyframes(str(clip), tmp_path / "f", max_frames=10)
    assert meta["engine"] == "uniform" and meta["fallback"] is True
    assert len(out) > 0 and calls["n"] >= 2


def test_empty_srt_cue_does_not_emit_the_next_index_as_text(tmp_path: Path):
    """Codex round 2: an empty-bodied SRT cue read past the whitespace
    separator and took the NEXT cue's numeric index as its payload, emitting a
    phantom segment whose text was "2"."""
    srt = tmp_path / "phantom.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n \n"
        "2\n00:00:01,000 --> 00:00:02,000\nreal\n\n",
        encoding="utf-8",
    )
    segs = T.parse_subtitle(srt)
    assert [s["text"] for s in segs] == ["real"], segs
    assert segs[0]["start"] == 1.0


def test_a_cue_whose_text_is_a_number_survives(tmp_path: Path):
    """The index guard must not eat a legitimate numeric caption: it only
    applies when the very next line is a timestamp."""
    vtt = tmp_path / "numeric.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n42\n\n"
        "00:00:01.000 --> 00:00:02.000\nnext\n\n",
        encoding="utf-8",
    )
    assert [s["text"] for s in T.parse_subtitle(vtt)] == ["42", "next"]


def test_frame_count_boundary_rounds_half_up(tmp_path: Path, monkeypatch):
    """Codex round 2: `round()` ties-to-even made exactly cap + 0.5 (e.g. a
    predicted 10.5 against a cap of 10) read as 10, so the rate was left alone
    and ffmpeg's 11th frame truncated the tail. Half-up closes it."""
    monkeypatch.setattr(F, "_extract_span_seconds", lambda *a, **k: 21.0)
    seen = {}
    real_run = subprocess.run

    def capture(cmd, *a, **kw):
        for j, tok in enumerate(cmd):
            if tok == "-vf":
                seen["vf"] = cmd[j + 1]
        return real_run(cmd, *a, **kw)

    clip = tmp_path / "c.mp4"
    real_run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
              "-i", "testsrc=size=160x120:duration=21:rate=10",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    monkeypatch.setattr(F.subprocess, "run", capture)
    # 0.5 fps over a 21s span predicts exactly 10.5 frames against a cap of 10.
    F.extract(str(clip), tmp_path / "f", fps=0.5, resolution=128, max_frames=10)
    rate = float(seen["vf"].split("fps=")[1].split(",")[0])
    assert rate < 0.5, f"rate not lowered at the cap+0.5 boundary: {rate}"
