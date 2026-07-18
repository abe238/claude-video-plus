"""Evidence compiler: dedup, auto-policy, roll-up + numeric guard, sufficiency,
coverage, manifest schema, fail-open exit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import evidence


# --- fixtures: tiny synthetic VTT + chapters info ------------------------------

def _vtt_stamp(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.000"


def make_vtt(path: Path, cues) -> None:
    lines = ["WEBVTT", ""]
    for start, end, text in cues:
        lines += [f"{_vtt_stamp(start)} --> {_vtt_stamp(end)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


CUES = [
    (0, 6, "welcome back to the channel everyone"),
    (8, 14, "today we have a bunch of stories to get through"),
    (16, 22, "let's jump right in"),
    (60, 66, "the new model is here and the new model is a big deal"),
    (70, 76, "it has new features new modes and a new app surface with new tools"),
    (95, 101, "the pricing structure changed and the cost is lower now"),
    (105, 111, "as you can see on the screen it is quite something"),
    (180, 186, "now for something completely different a drawing demo"),
    (200, 206, "the api runs at $5 per million tokens which is wild"),
    (240, 246, "this thing is really fast much faster than anything else"),
    (270, 276, "that wraps up the demo section"),
]

INFO = {
    "duration": 300,
    "chapters": [
        {"start_time": 0.0, "end_time": 60.0, "title": "Intro"},
        {"start_time": 60.0, "end_time": 180.0, "title": "New Model"},
        {"start_time": 180.0, "end_time": 300.0, "title": "Drawing App Demo"},
    ],
}


@pytest.fixture
def artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    vtt = tmp_path / "video.en.vtt"
    make_vtt(vtt, CUES)
    info = tmp_path / "video.info.json"
    info.write_text(json.dumps(INFO), encoding="utf-8")
    video = tmp_path / "video.mp4"  # never decoded: extract_frame is stubbed
    video.write_bytes(b"")

    def fake_extract(video_path, ts, path):
        Path(path).write_bytes(b"jpg")
        return True

    monkeypatch.setattr(evidence, "extract_frame", fake_extract)
    return {"vtt": str(vtt), "info": str(info), "video": str(video),
            "out": tmp_path / "out"}


def _manifest(out: Path) -> dict:
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


# --- dedup: rolling-caption overlap collapse -----------------------------------

def test_dedupe_rolling_collapses_overlap():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "hello world"},
        {"start": 2.0, "end": 4.0, "text": "world blah"},   # prev tail == first half
        {"start": 4.0, "end": 6.0, "text": "lo wor"},        # contained in prev
        {"start": 6.0, "end": 8.0, "text": "a completely different line"},
    ]
    out = evidence.dedupe_rolling(segs)
    assert [s["text"] for s in out] == ["hello world", "a completely different line"]
    assert out[0]["end"] == 6.0  # dropped cues extend the keeper's range


def test_dedupe_rolling_empty_is_noop():
    assert evidence.dedupe_rolling([]) == []


def test_dedupe_strips_repeated_prefix():
    # YouTube rolling cues re-emit the previous cue's last line as the next
    # cue's first line; the repeat is often shorter than half the cue, so the
    # drop rules miss it and the prefix must be stripped instead.
    segs = [
        {"start": 0.0, "end": 3.0, "text": "alpha bravo charlie delta golf hotel india"},
        {"start": 3.0, "end": 6.0,
         "text": "golf hotel india juliet kilo lima mike november oscar"},
    ]
    out = evidence.dedupe_rolling(segs)
    assert [s["text"] for s in out] == [
        "alpha bravo charlie delta golf hotel india",
        "juliet kilo lima mike november oscar",
    ]


# --- chapter roll-up: greedy keeps trying smaller chapters -----------------------

def _seg(chapter, start, text):
    return {"chapter": chapter, "start": start, "text": text}


def test_rollup_skips_oversized_chapter_but_keeps_smaller_fit():
    segments = [
        _seg(0, 0.0, "x" * 30),
        _seg(1, 60.0, "y" * 300),  # oversized: must not lock out chapter 2
        _seg(2, 120.0, "z" * 30),
    ]
    ch_scores = {0: [3.0], 1: [2.0], 2: [1.0]}
    assert evidence.rollup_chapters([0, 1, 2], ch_scores, segments, 100) == [0, 2]


def test_rollup_stops_at_zero_score_chapters():
    segments = [_seg(0, 0.0, "x" * 10), _seg(1, 60.0, "y" * 10)]
    ch_scores = {0: [3.0], 1: [0.0]}
    assert evidence.rollup_chapters([0, 1], ch_scores, segments, 10**6) == [0]


# --- auto-policy classification -------------------------------------------------

@pytest.mark.parametrize("q", [
    "Summarize this video for me",
    "Give me an overview",
    "What are the main stories covered?",
    "Tell me everything",
    "all the announcements please",
])
def test_auto_policy_coverage(q):
    assert evidence.resolve_policy(q, "auto") == "coverage"


@pytest.mark.parametrize("q", [
    "How much does GPT-5.6 cost?",
    "What is the new Super App and what does it do?",
])
def test_auto_policy_targeted(q):
    assert evidence.resolve_policy(q, "auto") == "targeted"


def test_explicit_policy_overrides_auto():
    assert evidence.resolve_policy("Summarize this video", "targeted") == "targeted"


# --- targeted: numeric guard rescues pricing outside the top chapter ------------

def test_numeric_guard_rescues_pricing_outside_top_chapter(artifacts):
    summary = evidence.compile_evidence(
        artifacts["vtt"], artifacts["video"], artifacts["info"],
        "How much does the new model cost?", artifacts["out"],
        policy="targeted", text_budget=100,  # tiny budget -> top-1 chapter only
    )
    assert summary["selected_chapters"] == ["New Model"]

    manifest = _manifest(artifacts["out"])
    guards = [e for e in manifest["evidence"]
              if e["reason"] == "numeric-guard" and e["modalities"] == ["transcript"]]
    assert len(guards) == 1
    assert guards[0]["chapter"] == "Drawing App Demo"  # outside the selection
    # numbers are usually on screen: the guarded span gets a midpoint frame
    assert any(e["reason"] == "numeric-guard" and e["modalities"] == ["frame"]
               for e in manifest["evidence"])
    report = (artifacts["out"] / "report.txt").read_text(encoding="utf-8")
    assert "$5 per million tokens" in report


# --- targeted: sufficiency expansion for an uncovered facet ---------------------

def test_sufficiency_expansion_fires_for_uncovered_facet(artifacts):
    evidence.compile_evidence(
        artifacts["vtt"], artifacts["video"], artifacts["info"],
        "how fast is the new model", artifacts["out"],
        policy="targeted", text_budget=100,
    )
    manifest = _manifest(artifacts["out"])
    # Selection (New Model chapter) has no speed terms; guard grabs the $5 span
    # (also speed-free), so the speed facet must trigger an expansion.
    expansions = [e for e in manifest["evidence"] if e["reason"] == "facet-expansion"]
    assert expansions
    assert any(e["t_start"] == "04:00" for e in expansions)  # the "really fast" span
    report = (artifacts["out"] / "report.txt").read_text(encoding="utf-8")
    assert "really fast much faster" in report


# --- targeted: span rescue pulls question hits outside selected chapters --------

def test_span_rescue_pulls_relevant_span_outside_selected_chapter(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_vtt(tmp_path / "v.vtt", [
        (0, 6, "welcome to the show today"),
        (60, 66, "the zorp gadget is amazing and everyone loves the zorp gadget"),
        (70, 76, "the zorp gadget has many parts inside"),
        (120, 126, "unrelated filler content goes here for a while"),
        (150, 156, "later we revisit the zorp gadget briefly one more moment"),
    ])
    (tmp_path / "v.info.json").write_text(json.dumps({
        "duration": 180,
        "chapters": [
            {"start_time": 0.0, "end_time": 60.0, "title": "Intro"},
            {"start_time": 60.0, "end_time": 120.0, "title": "Zorp"},
            {"start_time": 120.0, "end_time": 180.0, "title": "Other"},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(evidence, "extract_frame",
                        lambda v, ts, p: Path(p).write_bytes(b"jpg") or True)

    summary = evidence.compile_evidence(
        str(tmp_path / "v.vtt"), "v.mp4", str(tmp_path / "v.info.json"),
        "tell me about the zorp gadget", tmp_path / "out",
        policy="targeted", text_budget=120,  # Zorp fits, Other does not
    )
    assert summary["selected_chapters"] == ["Zorp"]
    manifest = _manifest(tmp_path / "out")
    rescues = [e for e in manifest["evidence"] if e["reason"] == "span-rescue"]
    assert [e["chapter"] for e in rescues] == ["Other"]
    report = (tmp_path / "out" / "report.txt").read_text(encoding="utf-8")
    assert "later we revisit the zorp gadget" in report


# --- coverage: full transcript + capped chapter-start frames --------------------

def test_coverage_full_transcript_and_capped_frames(artifacts):
    summary = evidence.compile_evidence(
        artifacts["vtt"], artifacts["video"], artifacts["info"],
        "Summarize this video - what are the main stories covered?",
        artifacts["out"], policy="auto", max_frames=2,
    )
    assert summary["policy"] == "coverage"

    report = (artifacts["out"] / "report.txt").read_text(encoding="utf-8")
    for _, _, text in CUES:
        assert text in report  # full transcript survives

    manifest = _manifest(artifacts["out"])
    frames = [e for e in manifest["evidence"] if e["modalities"] == ["frame"]]
    assert len(frames) == 2  # capped by --max-frames
    assert all(e["reason"] == "chapter-start" for e in frames)
    assert [e["t_start"] for e in frames] == ["00:10", "01:10"]  # start+10s
    assert manifest["reader_cost"]["frames"] == 2


# --- token budget: frame cap shrinks when the transcript is large ---------------

def test_frame_budget_trims_for_large_transcript():
    # The judged failure: 73577 chars + 32 frames blew a 26500-token cap.
    kept = evidence.fit_frame_budget(73577, 32)
    assert kept < 32
    est = 73577 * evidence.TOKENS_PER_CHAR + kept * evidence.TOKENS_PER_FRAME
    assert est <= evidence.EVIDENCE_TOKEN_CAP


def test_frame_budget_no_trim_for_small_transcript():
    assert evidence.fit_frame_budget(500, 32) == 32


def test_frame_budget_floors_at_min_frames():
    assert evidence.fit_frame_budget(10**7, 32) == evidence.MIN_FRAMES


# --- manifest schema -------------------------------------------------------------

def test_manifest_keys_present(artifacts):
    evidence.compile_evidence(
        artifacts["vtt"], artifacts["video"], artifacts["info"],
        "What is the new app?", artifacts["out"], policy="targeted",
    )
    m = _manifest(artifacts["out"])
    assert m["schema_version"] == 1
    assert m["policy"] == "targeted"
    for ch in m["chapters"]:
        assert set(ch) == {"title", "start", "end", "selected"}
    assert m["evidence"]
    for e in m["evidence"]:
        assert set(e) == {"t_start", "t_end", "chapter", "modalities",
                          "reason", "score", "frame"}
    assert set(m["reader_cost"]) == {"transcript_chars", "frames"}
    assert m["reader_cost"]["transcript_chars"] > 0


# --- fail-open: unhandled error exits 3 ------------------------------------------

def test_fail_open_exits_3_on_bad_vtt(tmp_path: Path, capsys):
    rc = evidence.main([
        "--vtt", str(tmp_path / "missing.vtt"),
        "--video", str(tmp_path / "video.mp4"),
        "--info", str(tmp_path / "info.json"),
        "--question", "anything",
        "--out-dir", str(tmp_path / "out"),
    ])
    assert rc == 3
    assert "fail-open" in capsys.readouterr().err


# --- L1 calibration finding: None subtitle path must fail loudly, not open('None')

def test_compile_evidence_rejects_missing_subtitle_path(tmp_path):
    """The media re-download can transiently return subtitle_path=None even when
    captions were fetched moments earlier (YouTube timedtext flake). That None
    used to be stringified into open('None') -> FileNotFoundError, which the
    fail-open wrapper reported as a confusing "[Errno 2] ... 'None'". It must be
    a clear ValueError so the fallback message says what actually happened."""
    with pytest.raises(ValueError, match="subtitle path"):
        evidence.compile_evidence(
            None, str(tmp_path / "v.mp4"), str(tmp_path / "i.json"),
            "what happens?", tmp_path / "out",
        )
