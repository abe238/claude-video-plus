"""Contract tests for frame-engine v2 (WATCH_FRAME_ENGINE=v2).

Written RED before implementation (L2 of docs/LOOP_CHAIN_2026-07-18.md; spec in
docs/plans/COMPETITIVE-PLAN-2026-07.md Release 1; migration list in L1 audit).

v2 bundles three mechanisms behind one flag, tuned jointly because their
constants share units:
- R1a comparator: RGB max-channel changed-cell % (grayscale mean is blind to
  equal-luma color cuts and averages small caption changes to ~zero).
- R1b dedup memory: sliding window of last N kept frames with a time horizon
  (previous-kept-only re-sends A in A-B-A cutaways; a horizon keeps a
  semantically meaningful *return* to A from being suppressed forever).
- R1c density floor: post-dedup gap-fill so slow screencasts can't have
  multi-minute uncovered stretches; hard-bounded to a share of the cap so the
  floor can never starve scene selection.
Prior art for the ideas: HUANGCHIHHUNGLeo/claude-real-video (MIT; reimplemented,
not copied).
"""
from __future__ import annotations

import pytest

import frames


# --- helpers: synthetic rgb24 16x16 thumbs (768 bytes) ------------------------

N = frames.DEDUP_THUMB * frames.DEDUP_THUMB  # 256 pixels


def rgb_thumb(r: int, g: int, b: int) -> bytes:
    return bytes([r, g, b]) * N


def thumb_with_patch(base: bytes, patch_pixels: int, r: int, g: int, b: int) -> bytes:
    """Copy of ``base`` with the first ``patch_pixels`` pixels replaced."""
    out = bytearray(base)
    for i in range(patch_pixels):
        out[i * 3 : i * 3 + 3] = bytes([r, g, b])
    return bytes(out)


# --- R1a: comparator contract -------------------------------------------------

def test_v2_delta_equal_luma_color_cut_is_distinct():
    """A red→green hard cut with similar luma reads as identical to a grayscale
    mean comparator. Max-channel per-pixel deltas must flag every cell."""
    a = rgb_thumb(200, 0, 0)
    b = rgb_thumb(0, 200, 0)
    assert frames._changed_cell_pct(a, b) == pytest.approx(100.0)


def test_v2_delta_caption_swap_is_distinct():
    """A caption line touching ~6% of pixels averages to ~nothing under mean
    diff. Changed-cell % counts those pixels directly."""
    base = rgb_thumb(30, 30, 30)
    swapped = thumb_with_patch(base, patch_pixels=16, r=250, g=250, b=250)  # 16/256 = 6.25%
    pct = frames._changed_cell_pct(base, swapped)
    assert pct == pytest.approx(6.25)
    assert pct > frames.V2_CHANGED_PCT_THRESHOLD


def test_v2_delta_grain_is_duplicate():
    """Uniform sensor grain moves every channel a little; no cell crosses the
    per-cell tolerance, so the frame is a duplicate."""
    a = rgb_thumb(100, 100, 100)
    b = rgb_thumb(103, 98, 102)  # every delta well under V2_CELL_TOLERANCE
    assert frames._changed_cell_pct(a, b) == 0.0


def test_v2_delta_identical_is_zero_and_mismatch_is_max():
    a = rgb_thumb(9, 9, 9)
    assert frames._changed_cell_pct(a, a) == 0.0
    assert frames._changed_cell_pct(a, a[:-3]) == float("inf")  # fail-open: never collapse on decode hiccup


# --- R1b: window + horizon contract -------------------------------------------

def _cand(ts: float) -> dict:
    return {"timestamp_seconds": ts, "path": None}


def test_v2_window_drops_aba_within_horizon():
    """Interview cutaway: A(0s) B(5s) A(10s) — the return to A within the
    horizon is a duplicate. Old engine (last-kept-only) re-sent it."""
    A, B = rgb_thumb(200, 0, 0), rgb_thumb(0, 0, 200)
    kept = frames._dedupe_windowed(
        [_cand(0.0), _cand(5.0), _cand(10.0)], [A, B, A], delete=False,
    )
    assert [c["timestamp_seconds"] for c in kept] == [0.0, 5.0]


def test_v2_window_keeps_return_beyond_horizon():
    """A return to a shot AFTER the horizon is semantically meaningful (new
    segment, revisited slide) and must be kept."""
    A, B = rgb_thumb(200, 0, 0), rgb_thumb(0, 0, 200)
    beyond = frames.V2_WINDOW_HORIZON_SECONDS + 1.0
    kept = frames._dedupe_windowed(
        [_cand(0.0), _cand(5.0), _cand(beyond)], [A, B, A], delete=False,
    )
    assert [c["timestamp_seconds"] for c in kept] == [0.0, 5.0, beyond]


def test_v2_window_memory_is_bounded():
    """Only the last N kept frames are remembered: with N distinct frames in
    between, an old shot has aged out even inside the horizon."""
    # Steps of 60 per channel: every filler is decisively distinct from its
    # neighbors AND from A under the cell tolerance (a step of 10 would collapse).
    distinct = [rgb_thumb(min(255, 60 * i), max(0, 255 - 60 * i), 40) for i in range(1, frames.V2_WINDOW_SIZE + 1)]
    A = rgb_thumb(200, 0, 0)
    thumbs = [A, *distinct, A]
    cands = [_cand(float(i)) for i in range(len(thumbs))]
    kept = frames._dedupe_windowed(cands, thumbs, delete=False)
    assert len(kept) == len(thumbs)  # the second A survived: A aged out of the window


def test_v2_window_collapses_identical_run():
    A = rgb_thumb(77, 77, 77)
    kept = frames._dedupe_windowed([_cand(float(i)) for i in range(4)], [A, A, A, A], delete=False)
    assert [c["timestamp_seconds"] for c in kept] == [0.0]


# --- R1c: density floor contract ----------------------------------------------

def test_v2_floor_fills_oversized_gaps_from_dropped_pool():
    """Survivors at 0s and 300s with dropped candidates between: gap-fill
    reinstates dropped frames so no gap exceeds the interval."""
    survivors = [_cand(0.0), _cand(300.0)]
    dropped = [_cand(60.0), _cand(120.0), _cand(180.0), _cand(240.0)]
    filled = frames._gap_fill(survivors, dropped, floor_interval=100.0, max_fill=10)
    ts = [c["timestamp_seconds"] for c in filled]
    assert ts == sorted(ts)
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert max(gaps) <= 100.0


def test_v2_floor_respects_budget_share():
    """The floor may never starve scene selection: fills are hard-capped."""
    survivors = [_cand(0.0), _cand(1000.0)]
    dropped = [_cand(float(t)) for t in range(50, 1000, 50)]
    filled = frames._gap_fill(survivors, dropped, floor_interval=60.0, max_fill=3)
    assert len(filled) - len(survivors) <= 3


def test_v2_floor_noop_when_gaps_are_small():
    survivors = [_cand(float(t)) for t in range(0, 100, 10)]
    filled = frames._gap_fill(survivors, [_cand(5.0)], floor_interval=50.0, max_fill=10)
    assert filled == survivors


# --- flag routing --------------------------------------------------------------

def test_engine_defaults_to_v1(monkeypatch):
    monkeypatch.delenv("WATCH_FRAME_ENGINE", raising=False)
    assert frames.resolve_engine() == "v1"


def test_engine_env_selects_v2(monkeypatch):
    monkeypatch.setenv("WATCH_FRAME_ENGINE", "v2")
    assert frames.resolve_engine() == "v2"


def test_engine_unknown_value_falls_back_to_v1(monkeypatch):
    monkeypatch.setenv("WATCH_FRAME_ENGINE", "turbo")
    assert frames.resolve_engine() == "v1"


def test_flag_off_pipeline_is_unchanged(static_clip, tmp_path, monkeypatch):
    """With the flag off, selected timestamps must be identical to the v1
    engine's — byte-for-byte equivalence of the selection decision."""
    monkeypatch.delenv("WATCH_FRAME_ENGINE", raising=False)
    a, _ = frames.extract_scene_or_uniform(str(static_clip), tmp_path / "a", fps=1.0, target_frames=8)
    monkeypatch.setenv("WATCH_FRAME_ENGINE", "v1")
    b, _ = frames.extract_scene_or_uniform(str(static_clip), tmp_path / "b", fps=1.0, target_frames=8)
    assert [f["timestamp_seconds"] for f in a] == [f["timestamp_seconds"] for f in b]


def test_flag_on_pipeline_runs(cut_clip, tmp_path, monkeypatch):
    """Smoke: v2 end-to-end on a real clip keeps the distinct cuts."""
    monkeypatch.setenv("WATCH_FRAME_ENGINE", "v2")
    kept, meta = frames.extract_scene_or_uniform(str(cut_clip), tmp_path / "v2", fps=1.0, target_frames=8)
    assert len(kept) >= 2
    assert meta.get("frame_engine") == "v2"


# --- R1d: fps opt-out ----------------------------------------------------------

def test_user_fps_above_cap_is_honored():
    assert frames.resolve_user_fps(4.0) == 4.0


def test_user_fps_nonpositive_rejected():
    with pytest.raises(ValueError):
        frames.resolve_user_fps(0.0)
    with pytest.raises(ValueError):
        frames.resolve_user_fps(-1.0)


def test_auto_fps_still_capped():
    fps, _ = frames.auto_fps(3600.0)
    assert fps <= frames.MAX_FPS


# --- review hardening (Codex CONTINUE-WITH-CHANGES, 2026-07-18) ----------------

def test_v2_window_boundary_exactly_at_horizon_is_duplicate():
    """The horizon is inclusive: a return at exactly T is still suppressed."""
    A, B = rgb_thumb(200, 0, 0), rgb_thumb(0, 0, 200)
    at = frames.V2_WINDOW_HORIZON_SECONDS
    kept = frames._dedupe_windowed(
        [_cand(0.0), _cand(5.0), _cand(at)], [A, B, A], delete=False,
    )
    assert [c["timestamp_seconds"] for c in kept] == [0.0, 5.0]


def test_v2_floor_budget_test_is_not_tautological():
    """A no-op gap-fill must NOT pass the budget contract: fills are required
    when eligible, and exactly max_fill of them."""
    survivors = [_cand(0.0), _cand(1000.0)]
    dropped = [_cand(float(t)) for t in range(50, 1000, 50)]
    filled = frames._gap_fill(survivors, dropped, floor_interval=60.0, max_fill=3)
    assert len(filled) - len(survivors) == 3  # budget fully used, not skipped


def test_v2_partition_keeps_caption_swap_and_drops_grain():
    """End-to-end at partition level: the comparator decisions drive keep/drop."""
    base = rgb_thumb(30, 30, 30)
    caption = thumb_with_patch(base, patch_pixels=16, r=250, g=250, b=250)
    grain = rgb_thumb(33, 28, 32)
    kept = frames._dedupe_windowed(
        [_cand(0.0), _cand(1.0), _cand(2.0)], [base, caption, grain], delete=False,
    )
    # caption kept (distinct); grain dropped (dup of base, still in window)
    assert [c["timestamp_seconds"] for c in kept] == [0.0, 1.0]


def test_v2_delete_contract_removes_files_and_reindexes(tmp_path):
    """delete=True honors the same cleanup contract as v1 dedup: dropped JPEGs
    unlinked, survivors reindexed 0..n-1."""
    A, B = rgb_thumb(200, 0, 0), rgb_thumb(0, 0, 200)
    paths = []
    for i in range(3):
        p = tmp_path / f"frame_{i:04d}.jpg"
        p.write_bytes(b"jpegdata")
        paths.append(p)
    cands = [
        {"timestamp_seconds": 0.0, "path": str(paths[0]), "index": 0},
        {"timestamp_seconds": 5.0, "path": str(paths[1]), "index": 1},
        {"timestamp_seconds": 10.0, "path": str(paths[2]), "index": 2},
    ]
    kept = frames._dedupe_windowed(cands, [A, B, A], delete=True)
    assert [c["index"] for c in kept] == [0, 1]
    assert paths[0].exists() and paths[1].exists()
    assert not paths[2].exists()  # dropped A-return unlinked


def test_v2_floor_interval_is_computed_from_real_duration(cut_clip, tmp_path, monkeypatch):
    """L3 gate run 2 regression: the floor read a nonexistent metadata key
    ('duration' vs 'duration_seconds'), computed interval=None, and silently
    disabled BOTH halves of the density floor. Pin the plumbing."""
    monkeypatch.setenv("WATCH_FRAME_ENGINE", "v2")
    seen = {}
    real = frames.extract_scene_candidates
    def spy(*args, **kwargs):
        seen["floor_interval"] = kwargs.get("floor_interval")
        return real(*args, **kwargs)
    monkeypatch.setattr(frames, "extract_scene_candidates", spy)
    frames.extract_scene_or_uniform(str(cut_clip), tmp_path / "o", fps=1.0, target_frames=8, max_frames=100)
    assert seen["floor_interval"] and seen["floor_interval"] > 0
