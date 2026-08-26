"""--text-anchors: bounded transcript-segment frame anchors (absorbed from
claude-real-video, reimplemented with hard bounds per the Codex gpt-5.6-sol
review — memory bound, explicit-timestamp precedence, exact 30% floor).

Security property: no caption track — however pathological or hostile — can
drive an unbounded number of frame extractions OR an unbounded anchor list.
Caption TEXT is never read; only the numeric segment start.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from frames import caption_anchor_timestamps, text_anchor_limit

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts" / "watch.py"


def _segs(starts):
    return [{"start": s, "end": s + 0.5, "text": "x"} for s in starts]


# --- text_anchor_limit: precedence + exact 30% floor ------------------------


def test_uncapped_limit_is_100():
    assert text_anchor_limit(None, 0) == 100
    assert text_anchor_limit(None, 999) == 100  # manual count irrelevant uncapped


def test_exact_30pct_floor_is_zero_for_tiny_budgets():
    # floor(0.30 * b): 1,2,3 -> 0 ; not max(1, ...). Codex blocker 4.
    assert text_anchor_limit(1, 0) == 0
    assert text_anchor_limit(2, 0) == 0
    assert text_anchor_limit(3, 0) == 0
    assert text_anchor_limit(4, 0) == 1   # floor(1.2)
    assert text_anchor_limit(100, 0) == 30


def test_floor_is_exact_integer_math_for_huge_caps():
    # int(0.30*b) is float and wrong for large b; (3*b)//10 is exact. Codex re-review.
    for b in (9007199254739993, 9007199254740997, 10**18 + 7):
        assert text_anchor_limit(b, 0) == (3 * b) // 10


def test_explicit_timestamps_keep_precedence():
    # 8 manual cues out of a 10 budget -> anchors may take only the 2 remaining,
    # never the 3 that 30% would otherwise allow. Manual pins never evicted.
    assert text_anchor_limit(10, 8) == 2
    # manual already exhausts the budget -> zero anchors.
    assert text_anchor_limit(10, 10) == 0
    assert text_anchor_limit(10, 25) == 0
    # plenty of room -> the 30% floor is the binding limit.
    assert text_anchor_limit(100, 5) == 30


# --- caption_anchor_timestamps: filtering, thinning, capping ----------------


def test_empty_input_fails_open_to_empty():
    assert caption_anchor_timestamps([]) == []


def test_zero_max_anchors_returns_empty():
    assert caption_anchor_timestamps(_segs([1.0, 2.0]), max_anchors=0) == []


def test_basic_segment_starts_in_order():
    out = caption_anchor_timestamps(_segs([2.0, 5.0, 9.0]))
    assert out == [2.0, 5.0, 9.0]


def test_thinned_to_at_most_one_per_second_on_unrounded_time():
    # 0.0 kept; 0.3/0.9 within 1s; 1.0 kept; 1.5 within 1s of 1.0.
    out = caption_anchor_timestamps(_segs([0.0, 0.3, 0.9, 1.0, 1.5]))
    assert out == [0.0, 1.0]


def test_sub_second_rounding_does_not_defeat_thinning():
    # 0.004 and 0.006 would both round to ~0.0-0.01; thinning is on raw time so
    # only the first survives (they are <1s apart).
    out = caption_anchor_timestamps(_segs([0.004, 0.006, 1.2]))
    assert out == [0.0, 1.2]


def test_out_of_window_segments_dropped():
    out = caption_anchor_timestamps(_segs([1.0, 5.0, 20.0, 50.0]), lo=4.0, hi=25.0)
    assert out == [5.0, 20.0]


def test_non_finite_negative_and_bad_values_rejected():
    segs = _segs([3.0]) + [
        {"start": float("nan")}, {"start": float("inf")}, {"start": float("-inf")},
        {"start": -2.0}, {"start": None}, {"start": "not-a-number"}, {},
    ]
    out = caption_anchor_timestamps(segs, lo=0.0, hi=100.0)
    assert out == [3.0]


def test_over_cap_even_samples_first_and_last():
    out = caption_anchor_timestamps(_segs([i * 2.0 for i in range(500)]), max_anchors=100)
    assert len(out) == 100
    assert out[0] == 0.0
    assert out[-1] == 499 * 2.0  # last preserved, not head-truncated


def test_non_monotonic_straggler_is_skipped_not_reordered():
    # A late-arriving smaller start is dropped by the spacing gate; output stays
    # chronological without a full re-sort.
    out = caption_anchor_timestamps(_segs([0.0, 5.0, 1.0, 6.0]))
    assert out == [0.0, 5.0, 6.0]


# --- hostile input is hard-bounded in count AND memory ----------------------


def test_hostile_dense_track_is_hard_bounded_in_count():
    hostile = _segs([float(i) for i in range(10_000)])  # 10000s span, 1s apart
    assert len(caption_anchor_timestamps(hostile, max_anchors=100)) <= 100
    packed = _segs([i * 0.01 for i in range(10_000)])   # 100s span, thinned hard
    assert len(caption_anchor_timestamps(packed, max_anchors=100)) <= 100


def test_scan_is_bounded_so_pathological_cue_count_cannot_burn_cpu():
    # Far more "cues" than the scan bound: a generator proves we stop early
    # rather than materialize the whole thing.
    from frames import _MAX_ANCHOR_SCAN

    scanned = {"n": 0}

    def gen():
        # 1s-spaced so every scanned item is kept until the scan bound trips,
        # then even-sampled to max_anchors.
        i = 0
        while True:
            scanned["n"] = i + 1
            yield {"start": float(i)}
            i += 1

    out = caption_anchor_timestamps(gen(), max_anchors=50)
    assert len(out) == 50
    # enumerate pulls one item past the break; the bound holds within +1.
    assert scanned["n"] <= _MAX_ANCHOR_SCAN + 1


# --- positive control: a realistic caption track we SHOULD anchor -----------


def test_positive_control_realistic_caption_track_anchors():
    starts = [i * 4.0 for i in range(15)]  # 0,4,...,56 — 15 distinct states
    out = caption_anchor_timestamps(_segs(starts), hi=60.0, max_anchors=30)
    assert out == starts  # all anchored, nothing thinned or capped


# --- evidence-mode latch (Codex blocker 4) ----------------------------------


def test_evidence_request_latches_anchors_off_through_fallback():
    import watch
    # Evidence requested -> off, even though evidence may fall back to balanced.
    assert watch.text_anchors_enabled("evidence", True) is False
    # Genuinely balanced/other modes with the flag -> on.
    assert watch.text_anchors_enabled("balanced", True) is True
    assert watch.text_anchors_enabled("transcript", True) is True
    # Flag absent -> always off.
    assert watch.text_anchors_enabled("balanced", False) is False


# --- orchestration: resolve_text_anchors (budget, precedence, fail-open) -----


def _resolve(**kw):
    import watch
    base = dict(
        active=True, transcript_segments=_segs([2.0, 5.0, 9.0, 40.0]),
        have_video=True, lo=0.0, hi=1000.0, max_frames=20, manual_timestamps=[],
    )
    base.update(kw)
    return watch.resolve_text_anchors(**base)


def test_resolve_off_is_passthrough_no_status():
    # Flag off (or evidence-latched off) -> manual list untouched, no message.
    ts, status = _resolve(active=False, manual_timestamps=[3.0])
    assert ts == [3.0] and status is None


def test_resolve_no_captions_fails_open():
    ts, status = _resolve(transcript_segments=[], manual_timestamps=[3.0])
    assert ts == [3.0] and status == "no-captions"
    ts, status = _resolve(have_video=False, manual_timestamps=[3.0])
    assert ts == [3.0] and status == "no-captions"


def test_resolve_adds_bounded_anchors_and_keeps_manual():
    ts, status = _resolve(manual_timestamps=[100.0])
    assert status.startswith("added:")
    assert 100.0 in ts                      # manual preserved
    assert {2.0, 5.0, 9.0, 40.0} <= set(ts)  # anchors merged in
    assert len(ts) <= 20                    # never over the cap


def test_resolve_manual_precedence_bounds_anchor_count():
    # 18 manual cues, cap 20 -> anchors may take only 2 (20-18), never the 6
    # that 30% would allow; every manual cue survives.
    manual = [float(i) for i in range(200, 218)]  # 18 distinct, all in-window? hi=1000
    ts, status = _resolve(manual_timestamps=manual, transcript_segments=_segs([1.0, 3.0, 6.0, 9.0]))
    assert set(manual) <= set(ts)           # all 18 manual preserved
    added = len(set(ts) - set(manual))
    assert added <= 2                       # remaining budget only
    assert len(ts) <= 20


def test_resolve_budget_spent_when_manual_fills_cap():
    manual = [float(i) for i in range(20)]  # 20 manual, cap 20 -> no room
    ts, status = _resolve(manual_timestamps=manual)
    assert status == "budget-spent"
    assert set(ts) == set(manual)


def test_resolve_error_path_fails_open():
    class Boom:
        def __iter__(self):
            raise RuntimeError("hostile")
    ts, status = _resolve(transcript_segments=Boom(), manual_timestamps=[7.0])
    assert ts == [7.0] and status.startswith("error:")


# --- CLI surface: real registration, not a source grep ----------------------


def test_text_anchors_flag_is_really_registered():
    # A source grep would pass even if the arg were removed; --help proves the
    # parser actually accepts it.
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0
    assert "--text-anchors" in out.stdout
