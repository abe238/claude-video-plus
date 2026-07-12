#!/usr/bin/env python3
"""Deterministic reference calculations for v1 measurement gates."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable


WEIGHTS = {"correctness": 0.40, "completeness": 0.25, "citation": 0.25, "adherence": 0.10}
BOOTSTRAP_REPLICATES = 10_000
MIN_LATENCY_REPEATS = 30
MIN_P95_OBSERVATIONS = 20
MIN_CONFIRMATORY_FAMILIES = 5
MIN_CONFIRMATORY_FAMILIES_PER_CLASS = 3


def nearest_rank(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        raise ValueError("percentile requires at least one finite observation")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def p95(values: Iterable[float]) -> float:
    observations = list(values)
    if len(observations) < MIN_P95_OBSERVATIONS:
        raise ValueError(f"p95 requires at least {MIN_P95_OBSERVATIONS} observations")
    return nearest_rank(observations, 0.95)


def median(values: Iterable[float]) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        raise ValueError("median requires observations")
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def judge_score(judgment: dict) -> float:
    scores = judgment.get("scores", judgment)
    values = {name: int(scores[name]) for name in WEIGHTS}
    if any(value < 0 or value > 10 for value in values.values()):
        raise ValueError("judge rubric values must be integers from 0 to 10")
    return sum(WEIGHTS[name] * value for name, value in values.items())


def arm_score(judgments: list[dict]) -> float | None:
    valid = [judge_score(item) for item in judgments if not item.get("refused", False)]
    return sum(valid) / len(valid) if len(valid) >= 2 else None


def interval_iou(left: list[float], right: list[float]) -> float:
    start = max(float(left[0]), float(right[0]))
    end = min(float(left[1]), float(right[1]))
    intersection = max(0.0, end - start)
    union = max(float(left[1]), float(right[1])) - min(float(left[0]), float(right[0]))
    return intersection / union if union > 0 else 0.0


def evidence_metrics(gold: list[dict], selected: list[dict]) -> dict[str, float]:
    matched = 0
    interval_scores: list[float] = []
    for item in gold:
        if item["kind"] == "point":
            point = float(item["time"])
            hit = any(
                abs(float(candidate.get("time", math.inf)) - point) <= 2.0
                if candidate["kind"] == "point"
                else float(candidate["start"]) <= point <= float(candidate["end"])
                for candidate in selected
            )
            matched += int(hit)
            continue
        scores = [
            interval_iou([item["start"], item["end"]], [candidate["start"], candidate["end"]])
            for candidate in selected
            if candidate["kind"] == "interval"
        ]
        best = max(scores, default=0.0)
        interval_scores.append(best)
        matched += int(best >= 0.25)
    return {
        "recall": matched / len(gold) if gold else 1.0,
        "temporal_iou": sum(interval_scores) / len(interval_scores) if interval_scores else 1.0,
    }


def before_after_match(before: list[float], after: list[float], selected_times: list[float]) -> bool:
    before_hits = [time for time in selected_times if before[0] <= time <= before[1]]
    after_hits = [time for time in selected_times if after[0] <= time <= after[1]]
    return bool(before_hits and after_hits and min(before_hits) < max(after_hits))


def case_delta(case: dict) -> float | None:
    if case.get("both_failure"):
        return 0.0
    control = 0.0 if case.get("control_failure") else arm_score(case.get("control_judgments", []))
    candidate = 0.0 if case.get("candidate_failure") else arm_score(case.get("candidate_judgments", []))
    if control is None or candidate is None:
        return None
    return candidate - control


def clustered_bootstrap(family_deltas: dict[str, float], *, seed: int, replicates: int) -> dict[str, float]:
    families = sorted(family_deltas)
    if not families:
        raise ValueError("bootstrap requires at least one family")
    if replicates != BOOTSTRAP_REPLICATES:
        raise ValueError(f"bootstrap requires exactly {BOOTSTRAP_REPLICATES} replicates")
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        draw = [family_deltas[rng.choice(families)] for _ in families]
        samples.append(sum(draw) / len(draw))
    return {
        "mean": sum(family_deltas.values()) / len(family_deltas),
        "lower_95": nearest_rank(samples, 0.05),
    }


def latency_gate(noop: list[float], control: list[float], candidate: list[float]) -> dict[str, float | bool]:
    if min(len(noop), len(control), len(candidate)) < MIN_LATENCY_REPEATS:
        raise ValueError(f"latency gates require at least {MIN_LATENCY_REPEATS} repeats per arm")
    allowance = max(5.0, 0.05 * median(control), p95(noop) - median(noop))
    median_delta = median(candidate) - median(control)
    p95_delta = p95(candidate) - p95(control)
    return {"allowance_ms": allowance, "median_delta_ms": median_delta,
            "p95_delta_ms": p95_delta,
            "pass": median_delta <= allowance and p95_delta <= allowance}


def reduction(control: list[float], candidate: list[float]) -> float:
    baseline = median(control)
    if baseline <= 0:
        raise ValueError("token-reduction Control median must be positive")
    return (baseline - median(candidate)) / baseline


def asr_gate(data: dict) -> dict[str, bool | float]:
    required = ("control_wer", "candidate_wer", "control_boundary_median", "candidate_boundary_median",
                "control_boundary_p95", "candidate_boundary_p95", "language_wer_deltas")
    if any(name not in data for name in required):
        raise ValueError("ASR gate input is incomplete")
    overall_delta = float(data["candidate_wer"]) - float(data["control_wer"])
    language_ok = all(float(value) <= 2.0 for value in data["language_wer_deltas"].values())
    passed = (overall_delta <= 1.0 and language_ok
              and float(data["candidate_boundary_median"]) - float(data["control_boundary_median"]) <= 0.25
              and float(data["candidate_boundary_p95"]) - float(data["control_boundary_p95"]) <= 1.0)
    return {"wer_delta_points": overall_delta, "language_pass": language_ok, "pass": passed}


def evaluate_gates(inputs: dict, *, seed: int) -> dict:
    """Compute every release decision from preregistered aggregate inputs."""
    quality = clustered_bootstrap(inputs["quality_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
    quality_classes = {name: clustered_bootstrap(values, seed=seed, replicates=BOOTSTRAP_REPLICATES)
                       for name, values in inputs["quality_class_family_deltas"].items()}
    recall = clustered_bootstrap(inputs["recall_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
    citation = clustered_bootstrap(inputs["citation_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
    completion = {environment: int(values["candidate"]) >= int(values["control"])
                  for environment, values in inputs["completion_by_environment"].items()}
    token_reductions = {name: reduction(values["control"], values["candidate"])
                        for name, values in inputs["reader_tokens"].items()}
    latency = {name: latency_gate(values["noop"], values["control"], values["candidate"])
               for name, values in inputs["latency"].items()}
    asr = asr_gate(inputs["asr"])
    gates = {
        "quality": quality["lower_95"] > -0.25 and all(value["lower_95"] > -0.50 for value in quality_classes.values()),
        "recall": recall["lower_95"] > -0.02,
        "citation": citation["lower_95"] > -0.02,
        "completion": bool(completion) and all(completion.values()),
        "targeted_tokens": token_reductions.get("targeted", -math.inf) >= 0.50,
        "coverage_tokens": token_reductions.get("coverage", -math.inf) >= 0.25,
        "latency": bool(latency) and all(value["pass"] for value in latency.values()),
        "asr": bool(asr["pass"]),
        "blockers": not inputs["blocker_failures"],
    }
    pareto = (any(bool(value) for value in inputs["primary_improvements"].values())
              and all(gates.values()) and not inputs["strict_regressions"])
    return {"quality": quality, "quality_classes": quality_classes, "recall": recall,
            "citation": citation, "completion": completion, "token_reductions": token_reductions,
            "latency": latency, "asr": asr, "gates": gates, "pareto_promote": pareto}


def _paired_arm_values(rows: list[dict], value) -> dict[str, dict[str, float]]:
    paired: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row.get("arm") in {"control", "candidate"}:
            paired[row["case_id"]][row["arm"]] = float(value(row))
    return paired


def _family_deltas(cases: dict[str, dict], paired: dict[str, dict[str, float]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for case_id, arms in paired.items():
        if set(arms) == {"control", "candidate"}:
            grouped[cases[case_id]["source_family_id"]].append(arms["candidate"] - arms["control"])
    return {family: sum(values) / len(values) for family, values in grouped.items()}


def _asr_from_rows(rows: list[dict]) -> dict:
    paired = _paired_arm_values(
        rows,
        lambda row: 100.0 * (row["substitutions"] + row["deletions"] + row["insertions"])
        / row["reference_words"],
    )
    if not paired or any(set(arms) != {"control", "candidate"} for arms in paired.values()):
        raise ValueError("ASR evidence requires paired raw Control/Candidate rows")
    unavailable = [row for row in rows if not row["comparator_available"]]
    if unavailable:
        raise ValueError("ASR comparator unavailable; gate is not evaluable")
    control_wer = sum(arms["control"] for arms in paired.values()) / len(paired)
    candidate_wer = sum(arms["candidate"] for arms in paired.values()) / len(paired)
    boundaries: dict[str, list[float]] = {"control": [], "candidate": []}
    language_deltas: dict[str, list[float]] = defaultdict(list)
    by_case_arm = {(row["case_id"], row["arm"]): row for row in rows}
    for case_id, arms in paired.items():
        for arm in boundaries:
            boundaries[arm].extend(float(value) for value in by_case_arm[(case_id, arm)]["boundary_errors_seconds"])
        language = by_case_arm[(case_id, "candidate")]["language"]
        language_deltas[language].append(arms["candidate"] - arms["control"])
    return {
        "control_wer": control_wer,
        "candidate_wer": candidate_wer,
        "control_boundary_median": median(boundaries["control"]),
        "candidate_boundary_median": median(boundaries["candidate"]),
        "control_boundary_p95": p95(boundaries["control"]),
        "candidate_boundary_p95": p95(boundaries["candidate"]),
        "language_wer_deltas": {
            language: sum(values) / len(values) for language, values in language_deltas.items()
        },
    }


def derive_gate_result(records: list[dict], template: dict) -> dict:
    """Derive a schema-shaped gate result solely from canonical raw rows.

    ``template`` supplies frozen provenance, scope, thresholds, and raw-file receipts. It may not
    supply denominators, coverage, aggregates, or verdicts; those are recomputed here.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_type[row["artifact_type"]].append(row)
    cases = {row["case_id"]: row for row in by_type["case"]}
    if not cases:
        raise ValueError("gate evaluation requires canonical case rows")
    split = template["evaluation_split"]
    if any(row["split"] != split for row in cases.values()):
        raise ValueError("gate raw inputs contain a case outside the evaluation split")
    required_classes = set(template["required_classes"])
    required_environments = set(template["required_environments"])
    covered_classes = {row["question_class"] for row in cases.values()}
    families = {row["source_family_id"] for row in cases.values()}
    families_by_class = {
        name: {row["source_family_id"] for row in cases.values() if row["question_class"] == name}
        for name in covered_classes
    }
    if not required_classes.issubset(covered_classes):
        raise ValueError("raw cases do not cover every required class")
    if split == "confirmatory":
        declared = int(template["minimum_confirmatory_families"])
        if declared < MIN_CONFIRMATORY_FAMILIES or len(families) < declared:
            raise ValueError("underpowered confirmatory cohort overall")
        declared_by_class = template["minimum_confirmatory_families_by_class"]
        for name in required_classes:
            minimum = int(declared_by_class.get(name, 0))
            if minimum < MIN_CONFIRMATORY_FAMILIES_PER_CLASS or len(families_by_class[name]) < minimum:
                raise ValueError(f"underpowered confirmatory cohort for class {name}")

    final_runs: dict[tuple[str, str], dict] = {}
    for row in by_type["run"]:
        if row["case_id"] not in cases:
            raise ValueError(f"run references unrelated case {row['case_id']}")
        key = (row["case_id"], row["arm"])
        if key not in final_runs or row["attempt"] > final_runs[key]["attempt"]:
            final_runs[key] = row
    for case_id in cases:
        if any((case_id, arm) not in final_runs for arm in ("control", "candidate")):
            raise ValueError(f"case {case_id} lacks canonical paired runs")

    judgments: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in by_type["judgment"]:
        if row["case_id"] not in cases:
            raise ValueError(f"judgment references unrelated case {row['case_id']}")
        judgments[(row["case_id"], row["arm"])].append(row)
    quality_paired: dict[str, dict[str, float]] = defaultdict(dict)
    citation_paired: dict[str, dict[str, float]] = defaultdict(dict)
    for case_id in cases:
        for arm in ("control", "candidate"):
            run_failed = final_runs[(case_id, arm)]["result_state"] not in {"success", "degraded"}
            if run_failed:
                quality_paired[case_id][arm] = 0.0
                citation_paired[case_id][arm] = 0.0
                continue
            valid = [row for row in judgments[(case_id, arm)] if not row["refused"]]
            if len(valid) < 2:
                raise ValueError(f"case {case_id}/{arm} lacks two valid judgments")
            quality_paired[case_id][arm] = sum(judge_score(row) for row in valid) / len(valid)
            citation_paired[case_id][arm] = sum(row["scores"]["citation"] / 10 for row in valid) / len(valid)

    quality_family = _family_deltas(cases, quality_paired)
    citation_family = _family_deltas(cases, citation_paired)
    quality_classes = {
        name: _family_deltas(
            cases, {case_id: arms for case_id, arms in quality_paired.items()
                    if cases[case_id]["question_class"] == name}
        ) for name in required_classes
    }
    retrieval_paired = _paired_arm_values(
        by_type["retrieval"],
        lambda row: evidence_metrics(cases[row["case_id"]]["gold_evidence"] or [], row["selected_evidence"])["recall"],
    )
    if any(row["case_id"] not in cases for row in by_type["retrieval"]):
        raise ValueError("retrieval evidence references an unrelated case")
    recall_family = _family_deltas(cases, retrieval_paired)

    usage_paired = _paired_arm_values(
        by_type["usage"], lambda row: row["reader_text_tokens"] + row["reader_image_tokens"]
    )
    if any(row["case_id"] not in cases for row in by_type["usage"]):
        raise ValueError("usage evidence references an unrelated case")
    reader_tokens: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"control": [], "candidate": []})
    for case_id, arms in usage_paired.items():
        if set(arms) == {"control", "candidate"}:
            question_class = cases[case_id]["question_class"]
            for arm, value in arms.items():
                reader_tokens[question_class][arm].append(value)

    completion: dict[str, dict[str, int]] = defaultdict(lambda: {"control": 0, "candidate": 0})
    for (case_id, arm), row in final_runs.items():
        if row["result_state"] in {"success", "degraded"}:
            completion[row["environment_id"]][arm] += 1
    covered_environments = set(completion)
    if not required_environments.issubset(covered_environments):
        raise ValueError("raw runs do not cover every required environment")

    latency: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"noop": [], "control": [], "candidate": []}
    )
    for row in by_type["resource"]:
        if row["case_id"] not in cases:
            raise ValueError("resource evidence references an unrelated case")
        latency[f"{row['environment_id']}:{row['state']}"][row["arm"]].append(row["wall_ms"])
    complete_latency = {name: values for name, values in latency.items()
                        if min(len(values[arm]) for arm in ("noop", "control", "candidate")) >= MIN_LATENCY_REPEATS}

    if any(row.get("case_id") not in cases for row in by_type["asr"]):
        raise ValueError("ASR evidence references an unrelated case")
    asr_input = _asr_from_rows(by_type["asr"]) if template["asr_applicable"] else {
        "control_wer": 0, "candidate_wer": 0, "control_boundary_median": 0,
        "candidate_boundary_median": 0, "control_boundary_p95": 0,
        "candidate_boundary_p95": 0, "language_wer_deltas": {},
    }
    blockers = [row for row in by_type["failure"] if row["final_state"] in {"partial", "unavailable", "fatal"}]
    gate_inputs = {
        "quality_family_deltas": quality_family,
        "quality_class_family_deltas": quality_classes,
        "recall_family_deltas": recall_family,
        "citation_family_deltas": citation_family,
        "completion_by_environment": completion,
        "reader_tokens": reader_tokens,
        "latency": complete_latency,
        "asr": asr_input,
        "blocker_failures": blockers,
        "primary_improvements": {
            "quality": sum(quality_family.values()) / len(quality_family) > 0.10,
            "reader_tokens": any(reduction(v["control"], v["candidate"]) > 0.02 for v in reader_tokens.values()),
        },
        "strict_regressions": [],
    }
    derived = evaluate_gates(gate_inputs, seed=int(template["bootstrap_seed"]))
    if not complete_latency:
        derived["gates"]["latency"] = False
        derived["pareto_promote"] = False
    install_ok = bool(by_type["install_result"]) and all(
        row["exit_code"] == 0 for row in by_type["install_result"]
    )
    privacy_ok = bool(by_type["privacy_scan"]) and all(
        row["pass"] and row["observed_matches"] == 0 for row in by_type["privacy_scan"]
    )
    provenance_ok = bool(by_type["provenance"])
    if template["gate_scope"] == "release":
        derived["gates"].update(install=install_ok, privacy=privacy_ok, provenance=provenance_ok)
        derived["pareto_promote"] = derived["pareto_promote"] and install_ok and privacy_ok and provenance_ok
    denominators = {
        "cases": len(cases), "families": len(families),
        "cases_by_class": {name: sum(row["question_class"] == name for row in cases.values())
                           for name in sorted(covered_classes)},
        "families_by_class": {name: len(families_by_class[name]) for name in sorted(covered_classes)},
        "runs": len(by_type["run"]), "judgments": len(by_type["judgment"]),
        "retrieval_rows": len(by_type["retrieval"]), "usage_rows": len(by_type["usage"]),
        "resource_rows": len(by_type["resource"]), "failed_rows": len(blockers),
    }
    common = {name: template[name] for name in (
        "schema_version", "artifact_type", "created_at_utc", "packet_id", "requirement_ids",
        "control_commit", "candidate_commit", "candidate_config_hash", "plan_sha256",
        "environment_id", "tool_versions", "command_or_protocol", "status",
        "evaluator_version", "gate_scope", "asr_applicable", "evaluation_split",
        "bootstrap_seed", "minimum_confirmatory_families", "minimum_confirmatory_families_by_class",
        "margins", "raw_inputs", "raw_input_checksums", "required_classes", "required_environments",
    )}
    return {
        **common, "denominators": denominators,
        "aggregates": {name: derived[name] for name in (
            "quality", "quality_classes", "recall", "citation", "completion",
            "token_reductions", "latency", "asr",
        )},
        "gates": derived["gates"], "pareto_promote": derived["pareto_promote"],
        "covered_classes": sorted(covered_classes),
        "covered_environments": sorted(covered_environments),
    }


def evaluate_fixture(data: dict) -> dict:
    grouped: dict[str, list[float]] = defaultdict(list)
    completion = {"control": 0, "candidate": 0, "total": len(data["cases"])}
    evidence = {}
    for case in data["cases"]:
        if not case.get("control_failure") and not case.get("both_failure"):
            completion["control"] += 1
        if not case.get("candidate_failure") and not case.get("both_failure"):
            completion["candidate"] += 1
        delta = case_delta(case)
        if delta is not None:
            grouped[case["family_id"]].append(delta)
        if "gold" in case:
            evidence[case["id"]] = evidence_metrics(case["gold"], case.get("selected", []))
            if "before" in case:
                evidence[case["id"]]["before_after"] = before_after_match(
                    case["before"], case["after"], case.get("selected_times", [])
                )
    family_deltas = {family: sum(values) / len(values) for family, values in grouped.items()}
    return {
        "family_deltas": family_deltas,
        "quality": clustered_bootstrap(
            family_deltas, seed=int(data["seed"]), replicates=int(data["replicates"])
        ),
        "completion": completion,
        "evidence": evidence,
        "p95_fixture": p95(data["p95_values"]),
        "gate_results": evaluate_gates(data["gate_inputs"], seed=int(data["seed"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    result = evaluate_fixture(json.loads(args.fixture.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
