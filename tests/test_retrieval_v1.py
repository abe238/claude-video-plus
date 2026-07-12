import json

import pytest

from question import WatchRequest
from retrieval import conflicts, lexical_rank, obligations, progressive_expand, read_scout, write_scout
from semantic import hashed_local_rank, reciprocal_rank_fusion, remote_rank, uncertainty
from vision import VisualCandidate, ablation_receipt, select


SEGMENTS = [
    {"start": 0, "end": 5, "text": "Before launch the price was $20 and uploads were not supported."},
    {"start": 6, "end": 10, "text": "After launch the Pro price is $25 and uploads are supported."},
    {"start": 11, "end": 15, "text": "The dashboard changes from blue to green."},
]


def test_request_json_roundtrip_and_unknown_refusal(tmp_path):
    request = WatchRequest("video.mp4", "what changed?\ninclude price", "evidence", 1000, 4)
    path = tmp_path / "request.json"
    path.write_text(request.to_json(), encoding="utf-8")
    assert WatchRequest.from_file(path) == request
    path.write_text(json.dumps({"source": "x", "surprise": True}))
    with pytest.raises(ValueError, match="unknown"):
        WatchRequest.from_file(path)


def test_lexical_exactness_temporal_and_bounded_expansion():
    ranked = lexical_rank("What was the price before and after, and was upload not supported?", SEGMENTS)
    assert ranked[0]["segment"]["start"] in {0, 6}
    assert obligations("price before and after, not supported") == ["answer", "negation", "before-state", "after-state"]
    expanded = progressive_expand("price before and after", ranked, SEGMENTS, {ranked[0]["index"]}, 2)
    assert expanded["bounded"]
    assert len(expanded["expansions"]) <= 2


def test_scout_is_checksum_bound(tmp_path):
    path = tmp_path / "scout.json"
    write_scout(path, "a" * 64, SEGMENTS)
    assert read_scout(path, "a" * 64)
    payload = json.loads(path.read_text())
    payload["segments"][0]["text"] = "tampered"
    path.write_text(json.dumps(payload))
    assert read_scout(path, "a" * 64) is None


def test_semantic_is_triggered_only_on_uncertainty_and_remote_requires_authorization():
    scores, receipt = hashed_local_rank("price", ["pricing", "weather"])
    assert len(scores) == 2 and receipt.transmitted_bytes == 0
    assert uncertainty([], ["answer"])
    with pytest.raises(PermissionError):
        remote_rank("https://example.com/rank", "m", "q", ["x"], authorized=False)
    assert reciprocal_rank_fusion([[2, 1], [1, 2]])[0][0] == 1


def test_dependency_free_vision_selection_and_pareto_gate():
    candidates = [VisualCandidate(1, scene_delta=.8), VisualCandidate(1.2, scene_delta=.7),
                  VisualCandidate(5, transcript_cue=True)]
    assert [item.timestamp for item in select(candidates, 2)] == [1, 5]
    control = {"event_recall": .8, "duplicate_rate": .2, "reader_tokens": 100,
               "answer_quality": 8, "wall_ms": 50, "install_bytes": 0}
    candidate = dict(control, event_recall=.9, duplicate_rate=.1, reader_tokens=90, wall_ms=40)
    receipt = ablation_receipt(control, candidate)
    assert receipt["pareto_promote"] and not receipt["opencv_included"]
