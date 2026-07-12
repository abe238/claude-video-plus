#!/usr/bin/env python3
"""Deterministic reference calculations for v1 measurement gates."""

from __future__ import annotations

import argparse
import hashlib
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


def _finite_observations(values: Iterable[float], *, label: str) -> list[float]:
    observations: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError(f"{label} requires finite numeric observations")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} requires finite numeric observations") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label} requires finite numeric observations")
        observations.append(number)
    return observations


def nearest_rank(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(_finite_observations(values, label="percentile"))
    if not ordered:
        raise ValueError("percentile requires at least one finite observation")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def p95(values: Iterable[float]) -> float:
    observations = _finite_observations(values, label="p95")
    if len(observations) < MIN_P95_OBSERVATIONS:
        raise ValueError(f"p95 requires at least {MIN_P95_OBSERVATIONS} observations")
    return nearest_rank(observations, 0.95)


def median(values: Iterable[float]) -> float:
    ordered = sorted(_finite_observations(values, label="median"))
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


def evaluate_jitter_fixture(data: dict) -> dict:
    """Replay the sealed, machine-readable latency fixture without accepting an allowance."""
    if data.get("schema_version") != 1 or data.get("fixture_type") != "latency-jitter-v1":
        raise ValueError("unknown jitter fixture version")
    if data.get("unit") != "ms":
        raise ValueError("jitter fixture requires milliseconds")
    buckets = data.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("jitter fixture requires buckets")
    seen: set[tuple[str, str, str]] = set()
    results: dict[str, dict[str, float | bool]] = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise ValueError("jitter fixture bucket must be an object")
        key = (bucket.get("environment_id"), bucket.get("state"), bucket.get("duration_bucket"))
        if not all(isinstance(value, str) and value for value in key):
            raise ValueError("jitter fixture bucket lacks environment/state/duration")
        if key in seen:
            raise ValueError("jitter fixture has duplicate bucket")
        seen.add(key)
        if any(name not in bucket for name in ("noop_ms", "control_ms", "candidate_ms")):
            raise ValueError("jitter fixture bucket lacks raw repeat series")
        if any("allowance" in name or "jitter" in name for name in bucket):
            raise ValueError("post-outcome jitter allowance is forbidden")
        results[":".join(key)] = latency_gate(bucket["noop_ms"], bucket["control_ms"], bucket["candidate_ms"])
    return {
        "evaluator_version": "v1",
        "fixture_sha256": hashlib.sha256(_canonical_json(data)).hexdigest(),
        "buckets": results,
        "pass": all(result["pass"] for result in results.values()),
    }


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
    """Compute frozen development or confirmatory decisions from canonical observations."""
    split = inputs.get("evaluation_split", "confirmatory")
    if split == "development":
        def paired_mean(values: dict[str, dict[str, float]]) -> dict[str, float | str]:
            deltas = [arms["candidate"] - arms["control"] for arms in values.values()]
            if not deltas:
                raise ValueError("development paired mean requires paired rows")
            return {"mean": sum(deltas) / len(deltas), "method": "paired_arithmetic_mean"}

        quality = paired_mean(inputs["quality_case_pairs"])
        quality_classes = {name: paired_mean(values) for name, values in inputs["quality_class_case_pairs"].items()}
        recall = paired_mean(inputs["recall_case_pairs"])
        citation = paired_mean(inputs["citation_case_pairs"])
        completion = {}
        for environment, values in inputs["completion_by_environment"].items():
            allowed_drop = min(1.0, 0.01 * int(values["total"]))
            completion[environment] = int(values["control"]) - int(values["candidate"]) <= allowed_drop
        quality_gate = quality["mean"] >= -0.25 and all(value["mean"] >= -0.50 for value in quality_classes.values())
        recall_gate = recall["mean"] >= -0.02
        citation_gate = citation["mean"] >= -0.02
    elif split == "confirmatory":
        quality = clustered_bootstrap(inputs["quality_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
        quality_classes = {name: clustered_bootstrap(values, seed=seed, replicates=BOOTSTRAP_REPLICATES)
                           for name, values in inputs["quality_class_family_deltas"].items()}
        recall = clustered_bootstrap(inputs["recall_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
        citation = clustered_bootstrap(inputs["citation_family_deltas"], seed=seed, replicates=BOOTSTRAP_REPLICATES)
        completion = {environment: int(values["candidate"]) >= int(values["control"])
                      for environment, values in inputs["completion_by_environment"].items()}
        quality_gate = quality["lower_95"] > -0.25 and all(value["lower_95"] > -0.50 for value in quality_classes.values())
        recall_gate = recall["lower_95"] > -0.02
        citation_gate = citation["lower_95"] > -0.02
    else:
        raise ValueError("unknown evaluation split")
    token_reductions = {name: reduction(values["control"], values["candidate"])
                        for name, values in inputs["reader_tokens"].items()}
    latency = {name: latency_gate(values["noop"], values["control"], values["candidate"])
               for name, values in inputs["latency"].items()}
    asr = asr_gate(inputs["asr"])
    before_after = inputs.get("before_after", {"pass": True, "required_pairs": 0})
    gates = {
        "quality": quality_gate,
        "recall": recall_gate,
        "citation": citation_gate,
        "before_after": bool(before_after["pass"]),
        "completion": bool(completion) and all(completion.values()),
        "latency": bool(latency) and all(value["pass"] for value in latency.values()),
        "asr": bool(asr["pass"]),
        "blockers": not inputs["blocker_failures"],
        "primary_improvement": any(bool(value) for value in inputs["primary_improvements"].values()),
    }
    if split == "confirmatory":
        gates.update(
            targeted_tokens=token_reductions.get("targeted", -math.inf) >= 0.50,
            coverage_tokens=token_reductions.get("coverage", -math.inf) >= 0.25,
        )
    pareto = (any(bool(value) for value in inputs["primary_improvements"].values())
              and all(gates.values()) and not inputs["strict_regressions"])
    return {"quality": quality, "quality_classes": quality_classes, "recall": recall,
            "citation": citation, "completion": completion, "token_reductions": token_reductions,
            "latency": latency, "asr": asr, "before_after": before_after,
            "strict_regressions": inputs["strict_regressions"], "gates": gates, "pareto_promote": pareto}


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


def _require_exact_pairs(rows: list[dict], cases: dict[str, dict], *, artifact: str) -> dict[str, dict[str, dict]]:
    """Require one raw Control/Candidate observation for every canonical case."""
    paired: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        case_id, arm = row.get("case_id"), row.get("arm")
        if case_id not in cases:
            raise ValueError(f"{artifact} evidence references an unrelated case")
        if arm not in {"control", "candidate"}:
            raise ValueError(f"{artifact} evidence has an invalid paired arm")
        if arm in paired[case_id]:
            raise ValueError(f"{artifact} evidence has duplicate paired rows for {case_id}/{arm}")
        paired[case_id][arm] = row
    for case_id in cases:
        if set(paired.get(case_id, {})) != {"control", "candidate"}:
            raise ValueError(f"case {case_id} lacks paired {artifact} rows")
    return paired


def paired_arm_order(case_id: str) -> tuple[str, str]:
    """P01's frozen SHA-256 parity rule: first digest byte even runs Control first."""
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id is required for deterministic paired order")
    first = "control" if hashlib.sha256(case_id.encode("utf-8")).digest()[0] % 2 == 0 else "candidate"
    return first, "candidate" if first == "control" else "control"


def _duration_bucket(case: dict) -> str:
    flags = case.get("explicit_flags")
    bucket = flags.get("duration_bucket") if isinstance(flags, dict) else None
    if not isinstance(bucket, str) or not bucket.strip():
        raise ValueError(f"case {case.get('case_id')!r} lacks a preregistered duration_bucket")
    return bucket


def _declared_duration_buckets(case: dict) -> set[str]:
    primary = _duration_bucket(case)
    flags = case["explicit_flags"]
    declared = flags.get("duration_buckets", [primary])
    if not isinstance(declared, list) or not declared or any(not isinstance(item, str) or not item for item in declared):
        raise ValueError(f"case {case.get('case_id')!r} has invalid declared duration buckets")
    if primary not in declared or len(set(declared)) != len(declared):
        raise ValueError(f"case {case.get('case_id')!r} has inconsistent declared duration buckets")
    return set(declared)


def _before_after_windows(case: dict) -> list[tuple[list[float], list[float]]]:
    flags = case.get("explicit_flags")
    raw = flags.get("before_after_windows", []) if isinstance(flags, dict) else []
    if not isinstance(raw, list):
        raise ValueError(f"case {case.get('case_id')!r} has invalid before/after windows")
    windows: list[tuple[list[float], list[float]]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"before", "after"}:
            raise ValueError(f"case {case.get('case_id')!r} has invalid before/after window")
        before, after = item["before"], item["after"]
        if not all(isinstance(value, list) and len(value) == 2 for value in (before, after)):
            raise ValueError(f"case {case.get('case_id')!r} has invalid before/after window")
        before_numbers = _finite_observations(before, label="before window")
        after_numbers = _finite_observations(after, label="after window")
        if before_numbers[1] <= before_numbers[0] or after_numbers[1] <= after_numbers[0]:
            raise ValueError(f"case {case.get('case_id')!r} has invalid before/after window")
        windows.append((before_numbers, after_numbers))
    return windows


def _selected_times(selected: list[dict]) -> list[float]:
    times: list[float] = []
    for item in selected:
        if item.get("kind") == "point":
            times.extend(_finite_observations([item.get("time")], label="selected point"))
        elif item.get("kind") == "interval":
            times.extend(_finite_observations([item.get("start"), item.get("end")], label="selected interval"))
        else:
            raise ValueError("selected evidence has unknown kind")
    return times


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
    case_rows = by_type["case"]
    cases = {row["case_id"]: row for row in case_rows}
    if not cases:
        raise ValueError("gate evaluation requires canonical case rows")
    if len(cases) != len(case_rows):
        raise ValueError("gate evaluation has duplicate canonical case IDs")
    split = template["evaluation_split"]
    if any(row["split"] != split for row in cases.values()):
        raise ValueError("gate raw inputs contain a case outside the evaluation split")
    required_classes = set(template["required_classes"])
    required_environments = set(template["required_environments"])
    if template.get("evaluator_version") != "v1":
        raise ValueError("unknown frozen evaluator version")
    margins = template.get("margins", {})
    if not isinstance(margins, dict) or any(
        "allowance" in str(name).lower() or "jitter" in str(name).lower() for name in margins
    ):
        raise ValueError("post-outcome latency allowances are forbidden")
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
    attempts: dict[tuple[str, str], set[int]] = defaultdict(set)
    runs_by_attempt: dict[tuple[str, str, int], dict] = {}
    for row in by_type["run"]:
        if row["case_id"] not in cases:
            raise ValueError(f"run references unrelated case {row['case_id']}")
        if row.get("arm") not in {"control", "candidate"}:
            raise ValueError("run evidence has an invalid paired arm")
        key = (row["case_id"], row["arm"])
        if not isinstance(row.get("attempt"), int) or row["attempt"] < 1:
            raise ValueError("run evidence has an invalid attempt")
        if row["attempt"] in attempts[key]:
            raise ValueError(f"run evidence has duplicate attempt for {key!r}")
        attempts[key].add(row["attempt"])
        runs_by_attempt[(row["case_id"], row["arm"], row["attempt"])] = row
        if key not in final_runs or row["attempt"] > final_runs[key]["attempt"]:
            final_runs[key] = row
    for case_id in cases:
        if any((case_id, arm) not in final_runs for arm in ("control", "candidate")):
            raise ValueError(f"case {case_id} lacks canonical paired runs")
    for key, observed in attempts.items():
        if observed != set(range(1, max(observed) + 1)):
            raise ValueError(f"case/arm {key!r} has a dropped attempt")
    attempts_by_case: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for (case_id, arm, attempt), row in runs_by_attempt.items():
        order = row.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order not in {1, 2}:
            raise ValueError("run attempt order must be 1 or 2")
        attempts_by_case[(case_id, attempt)][arm] = row
    for (case_id, attempt), arms in attempts_by_case.items():
        if set(arms) == {"control", "candidate"}:
            expected = {arm: index + 1 for index, arm in enumerate(paired_arm_order(case_id))}
            observed = {arm: row["order"] for arm, row in arms.items()}
            if set(observed.values()) != {1, 2}:
                raise ValueError(f"case {case_id} attempt {attempt} lacks unique orders 1/2")
            if observed != expected:
                raise ValueError(f"case {case_id} attempt {attempt} violates deterministic paired order")
        elif attempt == 1:
            raise ValueError(f"case {case_id} initial attempt lacks paired Control/Candidate runs")

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
    quality_case_classes = {
        name: {case_id: arms for case_id, arms in quality_paired.items()
               if cases[case_id]["question_class"] == name}
        for name in required_classes
    }
    retrieval_rows = _require_exact_pairs(by_type["retrieval"], cases, artifact="retrieval")
    retrieval_paired: dict[str, dict[str, float]] = defaultdict(dict)
    temporal_paired: dict[str, dict[str, float]] = defaultdict(dict)
    before_after_totals = {"control": 0, "candidate": 0, "required_pairs": 0, "false_drops": 0}
    for case_id, arms in retrieval_rows.items():
        windows = _before_after_windows(cases[case_id])
        before_after_totals["required_pairs"] += len(windows)
        pair_matches_by_arm: dict[str, list[bool]] = {}
        for arm, row in arms.items():
            metrics = evidence_metrics(cases[case_id]["gold_evidence"] or [], row["selected_evidence"])
            if not math.isclose(float(row["temporal_iou"]), metrics["temporal_iou"], rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"retrieval {case_id}/{arm} temporal_iou is not derived from selected evidence")
            pair_matches = [before_after_match(before, after, _selected_times(row["selected_evidence"]))
                            for before, after in windows]
            pair_matches_by_arm[arm] = pair_matches
            expected_before_after = all(pair_matches)
            if bool(row["before_after_match"]) != expected_before_after:
                raise ValueError(f"retrieval {case_id}/{arm} before_after_match is not derived from selected evidence")
            retrieval_paired[case_id][arm] = metrics["recall"]
            temporal_paired[case_id][arm] = metrics["temporal_iou"]
            before_after_totals[arm] += sum(pair_matches)
        before_after_totals["false_drops"] += sum(
            control and not candidate
            for control, candidate in zip(pair_matches_by_arm["control"], pair_matches_by_arm["candidate"])
        )
    recall_family = _family_deltas(cases, retrieval_paired)
    temporal_family = _family_deltas(cases, temporal_paired)
    recall_case_pairs = dict(retrieval_paired)

    usage_by_attempt: dict[tuple[str, str, int], dict] = {}
    for row in by_type["usage"]:
        attempt = row.get("attempt")
        key = (row.get("case_id"), row.get("arm"), attempt)
        if not isinstance(attempt, int) or attempt < 1:
            raise ValueError("usage evidence requires positive attempt identity")
        if key not in runs_by_attempt:
            raise ValueError(f"usage evidence has no matching run attempt {key!r}")
        if key in usage_by_attempt:
            raise ValueError(f"usage evidence has duplicate attempt {key!r}")
        _finite_observations([row[name] for name in (
            "reader_text_tokens", "reader_image_tokens", "all_model_input_tokens",
            "all_model_output_tokens", "calls", "dollars",
        )], label="usage")
        usage_by_attempt[key] = row
    if set(usage_by_attempt) != set(runs_by_attempt):
        raise ValueError("usage evidence must retain one row for every run attempt")
    usage_paired: dict[str, dict[str, float]] = defaultdict(dict)
    total_system_by_case: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    usage_metrics = ("reader_text_tokens", "reader_image_tokens", "all_model_input_tokens",
                     "all_model_output_tokens", "calls", "dollars")
    for case_id in cases:
        for arm in ("control", "candidate"):
            attempt_rows = [row for (row_case, row_arm, _), row in usage_by_attempt.items()
                            if (row_case, row_arm) == (case_id, arm)]
            totals = {name: sum(float(row[name]) for row in attempt_rows) for name in usage_metrics}
            total_system_by_case[case_id][arm] = totals
            usage_paired[case_id][arm] = totals["reader_text_tokens"] + totals["reader_image_tokens"]
    reader_tokens: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"control": [], "candidate": []})
    for case_id, arms in usage_paired.items():
        if set(arms) == {"control", "candidate"}:
            question_class = cases[case_id]["question_class"]
            for arm, value in arms.items():
                reader_tokens[question_class][arm].append(value)

    completion: dict[str, dict[str, int]] = defaultdict(lambda: {"control": 0, "candidate": 0, "total": 0})
    for case_id in cases:
        environments = {final_runs[(case_id, arm)]["environment_id"] for arm in ("control", "candidate")}
        if len(environments) != 1:
            raise ValueError(f"case {case_id} has Control/Candidate environment mismatch")
        environment = environments.pop()
        completion[environment]["total"] += 1
        for arm in ("control", "candidate"):
            if final_runs[(case_id, arm)]["result_state"] in {"success", "degraded"}:
                completion[environment][arm] += 1
    covered_environments = set(completion)
    if not required_environments.issubset(covered_environments):
        raise ValueError("raw runs do not cover every required environment")

    declared_durations = set().union(*(_declared_duration_buckets(case) for case in cases.values()))
    latency: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"noop": [], "control": [], "candidate": []})
    resource_values: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: {"noop": defaultdict(list), "control": defaultdict(list), "candidate": defaultdict(list)}
    )
    resource_repeat_keys: set[tuple[object, ...]] = set()
    workload_pairs: dict[tuple[object, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    workload_resource_attempts: set[tuple[str, str, int]] = set()
    resource_metrics = ("wall_ms", "cpu_ms", "peak_rss_bytes", "disk_bytes", "network_bytes", "process_calls", "initialization_ms")
    for row in by_type["resource"]:
        if row["case_id"] not in cases:
            raise ValueError("resource evidence references an unrelated case")
        if row.get("arm") not in {"noop", "control", "candidate"} or row.get("state") not in {"cold", "warm"}:
            raise ValueError("resource evidence has an invalid arm or state")
        if any(row.get(name) not in (None, "ms", "milliseconds") for name in ("unit", "wall_unit", "wall_ms_unit")):
            raise ValueError("resource evidence has mixed or non-millisecond wall units")
        attempt = row.get("attempt")
        if row["arm"] == "noop":
            if attempt != 0:
                raise ValueError("noop resource evidence requires benchmark attempt sentinel 0")
        elif not isinstance(attempt, int) or attempt < 1:
            raise ValueError("resource evidence requires positive attempt identity")
        if row["arm"] != "noop" and (row["case_id"], row["arm"], attempt) not in runs_by_attempt:
            raise ValueError("resource evidence has no matching workload run attempt")
        repeat_id = row.get("repeat_id")
        if not isinstance(repeat_id, (str, int)) or isinstance(repeat_id, bool) or str(repeat_id) == "":
            raise ValueError("resource evidence requires repeat_id")
        bucket = row.get("duration_bucket")
        if not isinstance(bucket, str) or bucket not in _declared_duration_buckets(cases[row["case_id"]]):
            raise ValueError("resource duration_bucket must be declared by its case")
        environment = row["environment_id"]
        repeat_key = (environment, row["state"], bucket, row["case_id"], row["arm"], attempt, repeat_id)
        if repeat_key in resource_repeat_keys:
            raise ValueError(f"duplicate resource repeat identity {repeat_key!r}")
        resource_repeat_keys.add(repeat_key)
        if row["arm"] == "noop":
            if row.get("pair_id") not in (None, ""):
                raise ValueError("noop resource evidence must not carry a workload pair_id")
            pass
        else:
            pair_id = row.get("pair_id")
            if pair_id not in (None, ""):
                if not isinstance(pair_id, (str, int)) or isinstance(pair_id, bool):
                    raise ValueError("workload resource pair_id must be a scalar or null")
                workload_pairs[(environment, row["state"], bucket, row["case_id"], pair_id)][row["arm"]] += 1
            workload_resource_attempts.add((row["case_id"], row["arm"], attempt))
        values = _finite_observations([row.get(name) for name in resource_metrics], label="resource")
        name = f"{environment}:{row['state']}:{bucket}"
        if row["arm"] == "noop" or row.get("pair_id") not in (None, ""):
            latency[name][row["arm"]].append(values[0])
        for metric, value in zip(resource_metrics, values):
            resource_values[name][row["arm"]][metric].append(value)
    for environment in required_environments:
        for bucket in declared_durations:
            for state in ("cold", "warm"):
                name = f"{environment}:{state}:{bucket}"
                values = latency.get(name, {})
                if any(len(values.get(arm, [])) < MIN_LATENCY_REPEATS for arm in ("noop", "control", "candidate")):
                    raise ValueError(f"latency bucket {name} lacks 30 no-op and paired workload repeats")
    if any(dict(arms) != {"control": 1, "candidate": 1} for arms in workload_pairs.values()):
        raise ValueError("resource workload pairs must contain exactly one Control and one Candidate repeat")
    if workload_resource_attempts != set(runs_by_attempt):
        raise ValueError("resource evidence must cover every run attempt")
    complete_latency = dict(latency)

    if any(row.get("case_id") not in cases for row in by_type["asr"]):
        raise ValueError("ASR evidence references an unrelated case")
    asr_input = _asr_from_rows(by_type["asr"]) if template["asr_applicable"] else {
        "control_wer": 0, "candidate_wer": 0, "control_boundary_median": 0,
        "candidate_boundary_median": 0, "control_boundary_p95": 0,
        "candidate_boundary_p95": 0, "language_wer_deltas": {},
    }
    failure_rows = by_type["failure"]
    failures_by_attempt: dict[tuple[str, str, int], dict] = {}
    for row in failure_rows:
        attempt = row.get("attempt")
        key = (row.get("case_id"), row.get("arm"), attempt)
        if not isinstance(attempt, int) or attempt < 1:
            raise ValueError("failure evidence requires positive attempt identity")
        if key not in runs_by_attempt:
            raise ValueError("failure evidence references an unrelated case or arm")
        if key in failures_by_attempt:
            raise ValueError(f"failure evidence has duplicate retained failure for {key!r}")
        failures_by_attempt[key] = row
    for key, run in runs_by_attempt.items():
        failed = run["result_state"] not in {"success", "degraded"}
        if failed and key not in failures_by_attempt:
            raise ValueError(f"failed run {key!r} lacks retained failure evidence")
        if not failed and key in failures_by_attempt:
            raise ValueError(f"successful run {key!r} cannot carry a final failure row")
    blockers = [row for row in failure_rows if row["final_state"] in {"partial", "unavailable", "fatal"}]

    before_after = {
        **before_after_totals,
        "control_recall": (before_after_totals["control"] / before_after_totals["required_pairs"]
                           if before_after_totals["required_pairs"] else 1.0),
        "candidate_recall": (before_after_totals["candidate"] / before_after_totals["required_pairs"]
                            if before_after_totals["required_pairs"] else 1.0),
        "pass": before_after_totals["false_drops"] == 0,
    }
    total_system: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {"control": {}, "candidate": {}})
    for question_class in covered_classes:
        for arm in ("control", "candidate"):
            for metric in usage_metrics:
                values = [total_system_by_case[case_id][arm][metric] for case_id in cases
                          if cases[case_id]["question_class"] == question_class]
                total_system[question_class][arm][metric] = median(values)
    resource_summary: dict[str, dict[str, dict[str, float]]] = {}
    for bucket, arms in resource_values.items():
        resource_summary[bucket] = {
            arm: {metric: median(values) for metric, values in metrics.items()}
            for arm, metrics in arms.items()
        }
    strict_regressions: list[str] = []
    paired_delta = lambda pairs: sum(arms["candidate"] - arms["control"] for arms in pairs.values()) / len(pairs)
    quality_delta = paired_delta(quality_paired) if split == "development" else sum(quality_family.values()) / len(quality_family)
    recall_delta = paired_delta(retrieval_paired) if split == "development" else sum(recall_family.values()) / len(recall_family)
    citation_delta = paired_delta(citation_paired) if split == "development" else sum(citation_family.values()) / len(citation_family)
    if quality_delta < -0.10:
        strict_regressions.append("answer_quality")
    if recall_delta < -0.01:
        strict_regressions.append("evidence_recall")
    if citation_delta < -0.01:
        strict_regressions.append("citation_support")
    for environment, values in completion.items():
        if values["candidate"] < values["control"]:
            strict_regressions.append(f"completion:{environment}")
    for question_class, arms in total_system.items():
        for metric in usage_metrics:
            control_value, candidate_value = arms["control"][metric], arms["candidate"][metric]
            threshold = 1.02 if metric in {
                "reader_text_tokens", "reader_image_tokens", "all_model_input_tokens",
                "all_model_output_tokens", "dollars",
            } else 1.0
            if (control_value == 0 and candidate_value > 0) or (
                control_value > 0 and candidate_value > control_value * threshold
            ):
                strict_regressions.append(f"total_system_{metric}:{question_class}")
    for bucket, result in complete_latency.items():
        latency_result = latency_gate(result["noop"], result["control"], result["candidate"])
        if not latency_result["pass"]:
            strict_regressions.append(f"latency:{bucket}")
    for bucket, arms in resource_summary.items():
        for metric in ("cpu_ms", "peak_rss_bytes", "disk_bytes", "network_bytes", "process_calls", "initialization_ms"):
            if arms["candidate"][metric] > arms["control"][metric]:
                strict_regressions.append(f"resource_{metric}:{bucket}")
    gate_inputs = {
        "evaluation_split": split,
        "quality_family_deltas": quality_family,
        "quality_class_family_deltas": quality_classes,
        "quality_case_pairs": quality_paired,
        "quality_class_case_pairs": quality_case_classes,
        "recall_family_deltas": recall_family,
        "recall_case_pairs": recall_case_pairs,
        "citation_family_deltas": citation_family,
        "citation_case_pairs": citation_paired,
        "completion_by_environment": completion,
        "reader_tokens": reader_tokens,
        "latency": complete_latency,
        "asr": asr_input,
        "before_after": before_after,
        "blocker_failures": blockers,
        "primary_improvements": {
            "quality": quality_delta > 0.10,
            "reader_tokens": any(reduction(v["control"], v["candidate"]) > 0.02 for v in reader_tokens.values()),
            "total_system_cost": any(
                values["control"]["dollars"] > 0
                and values["candidate"]["dollars"] < values["control"]["dollars"] * 0.98
                for values in total_system.values()
            ),
            "recall": any(
                sum(arms["candidate"] - arms["control"] for arms in values.values()) / len(values) > 0.01
                for values in ({case_id: arms for case_id, arms in retrieval_paired.items()
                                if cases[case_id]["question_class"] == name} for name in required_classes)
            ),
            "citation": any(
                sum(arms["candidate"] - arms["control"] for arms in values.values()) / len(values) > 0.01
                for values in ({case_id: arms for case_id, arms in citation_paired.items()
                                if cases[case_id]["question_class"] == name} for name in required_classes)
            ),
        },
        "strict_regressions": strict_regressions,
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
        "runs": len(by_type["run"]), "attempts": len(runs_by_attempt), "judgments": len(by_type["judgment"]),
        "retrieval_rows": len(by_type["retrieval"]), "usage_attempt_rows": len(usage_by_attempt),
        "resource_work_rows": len(by_type["resource"]), "failure_eligible_attempts": len(runs_by_attempt),
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
        "aggregates": {
            **{name: derived[name] for name in (
            "quality", "quality_classes", "recall", "citation", "completion",
            "token_reductions", "latency", "asr", "before_after", "strict_regressions",
            )},
            "temporal_iou": clustered_bootstrap(temporal_family, seed=int(template["bootstrap_seed"]),
                                                  replicates=BOOTSTRAP_REPLICATES),
            "total_system": total_system,
            "resources": resource_summary,
            "attempt_accounting": {
                "attempts": len(runs_by_attempt), "usage_attempt_rows": len(usage_by_attempt),
                "resource_work_rows": len(by_type["resource"]), "failed_attempts": len(failures_by_attempt),
            },
        },
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
    data = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = evaluate_jitter_fixture(data) if data.get("fixture_type") == "latency-jitter-v1" else evaluate_fixture(data)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
