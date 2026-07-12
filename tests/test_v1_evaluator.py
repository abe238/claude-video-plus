import json
from pathlib import Path

import pytest

from tools.evaluate_v1 import (
    clustered_bootstrap,
    evaluate_fixture,
    evaluate_gates,
    evaluate_jitter_fixture,
    judge_score,
    latency_gate,
    p95,
)


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
        "before_after": True, "targeted_tokens": True, "coverage_tokens": True, "latency": True,
        "asr": True, "blockers": True, "primary_improvement": True,
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


def test_latency_uses_exact_noop_spread_and_checks_median_and_p95_independently():
    noop = [10.0] * 28 + [20.0, 30.0]
    control = [100.0] * 30
    candidate = [104.0] * 28 + [120.0, 120.0]
    result = latency_gate(noop, control, candidate)
    assert result["allowance_ms"] == 10.0
    assert result["median_delta_ms"] == 4.0
    assert result["p95_delta_ms"] == 20.0
    assert result["pass"] is False


@pytest.mark.parametrize("values", [[1.0] * 19 + [float("nan")], [1.0] * 19 + [float("inf")]])
def test_percentiles_refuse_nonfinite_values_instead_of_laundering_them(values):
    with pytest.raises(ValueError, match="finite"):
        p95(values)


def test_machine_readable_jitter_fixture_replays_raw_series_without_custom_allowance():
    fixture = {
        "schema_version": 1,
        "fixture_type": "latency-jitter-v1",
        "unit": "ms",
        "buckets": [{
            "environment_id": "macos-arm64-python-3.14", "state": "warm", "duration_bucket": "short",
            "noop_ms": [10.0] * 30, "control_ms": [100.0] * 30, "candidate_ms": [104.0] * 30,
        }],
    }
    assert evaluate_jitter_fixture(fixture)["pass"] is True
    fixture["buckets"][0]["allowance_ms"] = 999
    with pytest.raises(ValueError, match="post-outcome"):
        evaluate_jitter_fixture(fixture)


def test_development_uses_paired_means_while_confirmatory_requires_completion_at_control():
    common = {
        "quality_family_deltas": {"family": 0.0},
        "quality_class_family_deltas": {"targeted": {"family": 0.0}},
        "recall_family_deltas": {"family": 0.0},
        "citation_family_deltas": {"family": 0.0},
        "quality_case_pairs": {"case": {"control": 8.0, "candidate": 8.0}},
        "quality_class_case_pairs": {"targeted": {"case": {"control": 8.0, "candidate": 8.0}}},
        "recall_case_pairs": {"case": {"control": 1.0, "candidate": 1.0}},
        "citation_case_pairs": {"case": {"control": 1.0, "candidate": 1.0}},
        "completion_by_environment": {"env": {"control": 200, "candidate": 199, "total": 200}},
        "reader_tokens": {"targeted": {"control": [100], "candidate": [40]}, "coverage": {"control": [100], "candidate": [70]}},
        "latency": {"bucket": {"noop": [1.0] * 30, "control": [100.0] * 30, "candidate": [100.0] * 30}},
        "asr": {"control_wer": 0, "candidate_wer": 0, "control_boundary_median": 0,
                "candidate_boundary_median": 0, "control_boundary_p95": 0, "candidate_boundary_p95": 0,
                "language_wer_deltas": {}},
        "before_after": {"pass": True}, "blocker_failures": [],
        "primary_improvements": {"reader_tokens": True}, "strict_regressions": [],
    }
    development = evaluate_gates({**common, "evaluation_split": "development"}, seed=17)
    confirmatory = evaluate_gates({**common, "evaluation_split": "confirmatory"}, seed=17)
    assert development["quality"]["method"] == "paired_arithmetic_mean"
    assert development["completion"]["env"] is True
    assert confirmatory["completion"]["env"] is False


def test_development_reports_modest_token_reduction_without_final_target_gate():
    common = {
        "quality_family_deltas": {"family": 0.2}, "quality_class_family_deltas": {"targeted": {"family": 0.2}},
        "recall_family_deltas": {"family": 0.0}, "citation_family_deltas": {"family": 0.0},
        "quality_case_pairs": {"case": {"control": 8.0, "candidate": 8.2}},
        "quality_class_case_pairs": {"targeted": {"case": {"control": 8.0, "candidate": 8.2}}},
        "recall_case_pairs": {"case": {"control": 1.0, "candidate": 1.0}},
        "citation_case_pairs": {"case": {"control": 1.0, "candidate": 1.0}},
        "completion_by_environment": {"env": {"control": 1, "candidate": 1, "total": 1}},
        "reader_tokens": {"targeted": {"control": [100], "candidate": [90]}, "coverage": {"control": [100], "candidate": [100]}},
        "latency": {"bucket": {"noop": [1.0] * 30, "control": [100.0] * 30, "candidate": [100.0] * 30}},
        "asr": {"control_wer": 0, "candidate_wer": 0, "control_boundary_median": 0,
                "candidate_boundary_median": 0, "control_boundary_p95": 0, "candidate_boundary_p95": 0,
                "language_wer_deltas": {}},
        "before_after": {"pass": True}, "blocker_failures": [],
        "primary_improvements": {"quality": True}, "strict_regressions": [],
    }
    development = evaluate_gates({**common, "evaluation_split": "development"}, seed=17)
    confirmatory = evaluate_gates({**common, "evaluation_split": "confirmatory"}, seed=17)
    assert development["gates"]["primary_improvement"] is True
    assert "targeted_tokens" not in development["gates"]
    assert confirmatory["gates"]["targeted_tokens"] is False
