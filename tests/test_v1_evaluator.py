import json
from pathlib import Path

import pytest

from tools.evaluate_v1 import clustered_bootstrap, evaluate_fixture, judge_score, latency_gate, p95


FIXTURE = Path(__file__).parent / "fixtures/v1_evaluator_golden.json"


def test_golden_v1_evaluator_result():
    result = evaluate_fixture(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert result["family_deltas"] == {"family-a": -3.5, "family-b": 7.0, "family-c": 0.0}
    assert result["quality"] == {"mean": 1.1666666666666667, "lower_95": -2.3333333333333335}
    assert result["completion"] == {"control": 3, "candidate": 3, "total": 5}
    assert result["evidence"] == {
        "valid-partial-overlap": {"recall": 1.0, "temporal_iou": 0.5, "before_after": True}
    }
    assert result["p95_fixture"] == 19.0
    assert result["gate_results"]["gates"] == {
        "quality": True, "recall": True, "citation": True, "completion": True,
        "targeted_tokens": True, "coverage_tokens": True, "latency": True,
        "asr": True, "blockers": True,
    }
    assert result["gate_results"]["pareto_promote"] is True


def test_schema_shaped_judgment_is_scored():
    assert judge_score({"scores": {"correctness": 8, "completeness": 8, "citation": 8, "adherence": 8}}) == 8


def test_p95_and_latency_reject_underpowered_inputs():
    with pytest.raises(ValueError, match="at least 20"):
        p95([1])
    with pytest.raises(ValueError, match="at least 30"):
        latency_gate([1] * 29, [1] * 30, [1] * 30)


def test_bootstrap_count_is_frozen():
    with pytest.raises(ValueError, match="exactly 10000"):
        clustered_bootstrap({"family": 0.0}, seed=1, replicates=9999)
