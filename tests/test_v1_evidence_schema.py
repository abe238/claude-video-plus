import copy
import hashlib

import json
from pathlib import Path

import pytest

from tools.evaluate_v1 import derive_gate_result
from tools.validate_v1_evidence import load_schema, validate_evidence_set, validate_record


def make_valid_record(schema, artifact_type):
    record = {name: copy.deepcopy(spec["example"]) for name, spec in schema["common_fields"].items()}
    record["artifact_type"] = artifact_type
    record.update({name: copy.deepcopy(spec["example"]) for name, spec in schema["artifacts"][artifact_type]["fields"].items()})
    if artifact_type in {"usage", "resource", "failure"}:
        record["attempt"] = 1
    if artifact_type == "resource":
        record.update(repeat_id="repeat-1", pair_id="pair-1", duration_bucket="short")
    return record


def test_valid_golden_record_for_every_artifact_type():
    schema = load_schema()
    for artifact_type in schema["artifacts"]:
        assert validate_record(make_valid_record(schema, artifact_type), schema) == [], artifact_type


def test_missing_artifact_field_is_rejected_for_every_type():
    schema = load_schema()
    for artifact_type, artifact in schema["artifacts"].items():
        record = make_valid_record(schema, artifact_type)
        del record[artifact["required"][0]]
        assert any("missing required" in error for error in validate_record(record, schema)), artifact_type


def test_complete_evidence_cannot_have_null_plan_hash():
    schema = load_schema()
    record = make_valid_record(schema, "baseline")
    record["plan_sha256"] = None
    assert "plan_sha256 may be null only for provisional evidence" in validate_record(record, schema)


def test_provisional_evidence_may_omit_frozen_identifiers():
    schema = load_schema()
    record = make_valid_record(schema, "baseline")
    record["status"] = "provisional"
    record["control_commit"] = None
    record["candidate_commit"] = None
    record["plan_sha256"] = None
    assert validate_record(record, schema) == []


def test_complete_fatal_run_rejects_missing_failure_and_unsafe_values():
    schema = load_schema()
    record = make_valid_record(schema, "run")
    record.update(attempt=-1, order=0, result_state="fatal", failure_class=None,
                  raw_manifest_path="../../missing.json")
    errors = validate_record(record, schema)
    assert any("attempt is outside" in error for error in errors)
    assert any("order is outside" in error for error in errors)
    assert any("safe relative" in error for error in errors)
    assert any("requires failure_class" in error for error in errors)


@pytest.mark.parametrize("artifact_type, field, expected", [
    ("usage", "attempt", "usage requires a positive attempt"),
    ("resource", "repeat_id", "resource requires repeat_id"),
    ("failure", "attempt", "failure requires a positive attempt"),
])
def test_runtime_attempt_and_repeat_fields_are_required_without_schema_edits(artifact_type, field, expected):
    schema = load_schema()
    record = make_valid_record(schema, artifact_type)
    record.pop(field)
    assert any(expected in error for error in validate_record(record, schema))


def test_passing_gate_rejects_empty_denominator_and_missing_input(tmp_path):
    schema = load_schema()
    record = make_valid_record(schema, "gate_result")
    record.update(denominators={}, gates={"release": True}, raw_inputs=["missing.jsonl"])
    path = tmp_path / "gate-results.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    errors = validate_evidence_set([path], schema)
    assert any("positive denominators" in error for error in errors)
    assert any("raw input does not exist" in error for error in errors)


def test_unpaired_runs_and_split_leakage_are_rejected(tmp_path):
    schema = load_schema()
    case_a = make_valid_record(schema, "case")
    case_a.update(case_id="a", source_family_id="family", split="development")
    case_b = make_valid_record(schema, "case")
    case_b.update(case_id="b", source_family_id="family", split="confirmatory")
    run = make_valid_record(schema, "run")
    run.update(case_id="a", arm="candidate", raw_manifest_path="manifest.json")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in (case_a, case_b, run)), encoding="utf-8")
    errors = validate_evidence_set([path], schema)
    assert any("lacks paired" in error for error in errors)
    assert any("leaks across" in error for error in errors)


def test_gate_raw_checksum_and_coverage_are_enforced(tmp_path):
    schema = load_schema()
    raw = tmp_path / "runs.jsonl"
    raw.write_text("{}\n", encoding="utf-8")
    record = make_valid_record(schema, "gate_result")
    record.update(
        raw_inputs=["runs.jsonl"], raw_input_checksums={"runs.jsonl": "0" * 64},
        required_classes=["targeted", "coverage"], covered_classes=["targeted"],
        required_environments=["macos-arm64-python-3.14", "ubuntu-x86_64-python-3.12"],
        covered_environments=["macos-arm64-python-3.14"],
    )
    path = tmp_path / "gate-results.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    errors = validate_evidence_set([path], schema)
    assert any("checksum mismatch" in error for error in errors)
    assert any("every required class" in error for error in errors)
    assert any("every required environment" in error for error in errors)

    record["raw_input_checksums"]["runs.jsonl"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    record["covered_classes"].append("coverage")
    record["covered_environments"].append("ubuntu-x86_64-python-3.12")
    path.write_text(json.dumps(record), encoding="utf-8")
    assert any("canonical raw inputs" in error for error in validate_evidence_set([path], schema))


def _canonical_gate_fixture(tmp_path: Path):
    schema = load_schema()
    gate = make_valid_record(schema, "gate_result")
    gate.update(
        packet_id="P03", requirement_ids=["MEAS-001"], gate_scope="measurement",
        asr_applicable=False, evaluation_split="development", bootstrap_seed=17,
        required_classes=["targeted"], required_environments=["macos-arm64-python-3.14"],
        minimum_confirmatory_families=5,
        minimum_confirmatory_families_by_class={"targeted": 3},
        margins={"quality": -0.25, "class_quality": -0.50, "recall": -0.02, "citation": -0.02},
    )

    def row(kind, **updates):
        value = make_valid_record(schema, kind)
        for field in ("packet_id", "requirement_ids", "control_commit", "candidate_commit",
                      "candidate_config_hash", "plan_sha256"):
            value[field] = copy.deepcopy(gate[field])
        value.update(status="complete", environment_id="macos-arm64-python-3.14", **updates)
        return value

    records = {
        "cases.jsonl": [row("case", case_id="case-1", source_family_id="family-1",
                             split="development", question_class="targeted", obligations=["answer"],
                             explicit_flags={"duration_bucket": "short"},
                             gold_evidence=[{"kind": "point", "time": 1.0}],
                             gold_unavailable_reason=None)],
        "runs.jsonl": [
            row("run", case_id="case-1", arm=arm, attempt=1, order=index,
                result_state="success", failure_class=None)
            for index, arm in enumerate(("control", "candidate"), 1)
        ],
        "judgments.jsonl": [
            row("judgment", case_id="case-1", arm=arm, arm_blinded=blind,
                position_order=position, scores={name: score for name in
                ("correctness", "completeness", "citation", "adherence")})
            for arm, blind, score in (("control", "A", 8), ("candidate", "B", 9))
            for position in (1, 2)
        ],
        "retrieval.jsonl": [
            row("retrieval", case_id="case-1", arm=arm,
                selected_evidence=[{"kind": "point", "time": 1.0}], temporal_iou=1.0,
                before_after_match=True)
            for arm in ("control", "candidate")
        ],
        "usage.jsonl": [
            row("usage", case_id="case-1", arm="control", reader_text_tokens=100,
                reader_image_tokens=0, all_model_input_tokens=100, attempt=1),
            row("usage", case_id="case-1", arm="candidate", reader_text_tokens=40,
                reader_image_tokens=0, all_model_input_tokens=40, attempt=1),
        ],
        "resources.jsonl": [
            row("resource", case_id="case-1", arm=arm, state=state, wall_ms=wall,
                attempt=0 if arm == "noop" else 1, repeat_id=f"{state}-{repeat}",
                pair_id=None if arm == "noop" else f"{state}-{repeat}", duration_bucket="short")
            for state in ("cold", "warm")
            for arm, wall in (("noop", 10.0), ("control", 100.0), ("candidate", 100.0))
            for repeat in range(1, 31)
        ],
        "failures.jsonl": [],
    }
    raw_inputs = []
    checksums = {}
    raw_rows = []
    for name, rows in records.items():
        raw = tmp_path / name
        raw.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in rows), encoding="utf-8")
        raw_inputs.append(name)
        checksums[name] = hashlib.sha256(raw.read_bytes()).hexdigest()
        raw_rows.extend(rows)
    gate.update(raw_inputs=raw_inputs, raw_input_checksums=checksums)
    gate = derive_gate_result(raw_rows, gate)
    gate_path = tmp_path / "gate-results.json"
    gate_path.write_text(json.dumps(gate, sort_keys=True), encoding="utf-8")
    return schema, gate, gate_path


def test_gate_is_recomputed_from_canonical_linked_raw_artifacts(tmp_path):
    schema, gate, gate_path = _canonical_gate_fixture(tmp_path)
    assert validate_record(gate, schema) == []
    assert validate_evidence_set([gate_path], schema) == []

    gate["denominators"]["cases"] = 99
    gate["covered_classes"] = ["targeted", "coverage"]
    gate["gates"]["quality"] = not gate["gates"]["quality"]
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    errors = validate_evidence_set([gate_path], schema)
    assert any("self-asserted denominators" in error for error in errors)
    assert any("self-asserted covered_classes" in error for error in errors)
    assert any("self-asserted gates" in error for error in errors)


@pytest.mark.parametrize("field, replacement", [
    ("denominators", {"cases": 2}),
    ("aggregates", {}),
    ("gates", {"quality": False}),
    ("pareto_promote", True),
    ("covered_classes", []),
    ("covered_environments", []),
])
def test_every_derived_gate_field_is_adversarially_recomputed(tmp_path, field, replacement):
    schema, gate, gate_path = _canonical_gate_fixture(tmp_path)
    gate[field] = (not gate[field]) if field == "pareto_promote" else replacement
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    errors = validate_evidence_set([gate_path], schema)
    assert any(f"self-asserted {field}" in error for error in errors)


@pytest.mark.parametrize("mutate, expected", [
    (lambda files: files.pop("failures.jsonl"), "missing canonical raw inputs"),
    (lambda files: files.update({"summary.json": "{}"}), "unrelated raw input"),
    (lambda files: files["runs.jsonl"].__setitem__(0, {**files["runs.jsonl"][0], "attempt": 2}), "dropped attempt"),
    (lambda files: files["resources.jsonl"].__setitem__(0, {**files["resources.jsonl"][0], "wall_ms": float("nan")}), "finite"),
])
def test_raw_linkage_and_measurement_mutations_are_refused(tmp_path, mutate, expected):
    schema, gate, gate_path = _canonical_gate_fixture(tmp_path)
    files = {
        name: [json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line]
        for name in gate["raw_inputs"]
    }
    mutate(files)
    for name, rows in files.items():
        raw = tmp_path / name
        if name.endswith(".json"):
            raw.write_text(rows if isinstance(rows, str) else json.dumps(rows), encoding="utf-8")
        else:
            raw.write_text("".join(json.dumps(row, allow_nan=True) + "\n" for row in rows), encoding="utf-8")
    gate["raw_inputs"] = list(files)
    gate["raw_input_checksums"] = {
        name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files
    }
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    assert any(expected in error for error in validate_evidence_set([gate_path], schema))


def test_latency_requires_each_cold_warm_duration_bucket_and_finite_ms(tmp_path):
    _, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    no_cold = [row for row in rows if not (row["artifact_type"] == "resource" and row["state"] == "cold")]
    with pytest.raises(ValueError, match="latency bucket"):
        derive_gate_result(no_cold, gate)

    mixed_unit = copy.deepcopy(rows)
    next(row for row in mixed_unit if row["artifact_type"] == "resource")["wall_unit"] = "seconds"
    with pytest.raises(ValueError, match="mixed"):
        derive_gate_result(mixed_unit, gate)

    with pytest.raises(ValueError, match="post-outcome"):
        derive_gate_result(rows, {**gate, "margins": {**gate["margins"], "jitter_allowance_ms": 999}})

    failed_attempt = copy.deepcopy(rows)
    next(row for row in failed_attempt if row["artifact_type"] == "run" and row["arm"] == "control").update(
        result_state="fatal", failure_class="timeout"
    )
    with pytest.raises(ValueError, match="retained failure"):
        derive_gate_result(failed_attempt, gate)


def test_attempt_repeat_and_declared_bucket_integrity_are_enforced(tmp_path):
    _, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)

    missing_attempt = copy.deepcopy(rows)
    next(row for row in missing_attempt if row["artifact_type"] == "usage").pop("attempt")
    with pytest.raises(ValueError, match="usage.*attempt"):
        derive_gate_result(missing_attempt, gate)

    duplicate_usage = copy.deepcopy(rows)
    duplicate_usage.append(copy.deepcopy(next(row for row in duplicate_usage if row["artifact_type"] == "usage")))
    with pytest.raises(ValueError, match="usage evidence has duplicate attempt"):
        derive_gate_result(duplicate_usage, gate)

    duplicate_repeat = copy.deepcopy(rows)
    resources = [row for row in duplicate_repeat if row["artifact_type"] == "resource" and row["arm"] == "control"]
    resources[1]["repeat_id"] = resources[0]["repeat_id"]
    with pytest.raises(ValueError, match="duplicate resource repeat"):
        derive_gate_result(duplicate_repeat, gate)

    duplicate_pair = copy.deepcopy(rows)
    resources = [row for row in duplicate_pair if row["artifact_type"] == "resource" and row["arm"] == "control"]
    resources[1]["pair_id"] = resources[0]["pair_id"]
    with pytest.raises(ValueError, match="workload pairs"):
        derive_gate_result(duplicate_pair, gate)

    missing_declared_bucket = copy.deepcopy(rows)
    case = next(row for row in missing_declared_bucket if row["artifact_type"] == "case")
    case["explicit_flags"]["duration_buckets"] = ["short", "long"]
    with pytest.raises(ValueError, match="long"):
        derive_gate_result(missing_declared_bucket, gate)

    failed_with_duplicates = copy.deepcopy(rows)
    next(row for row in failed_with_duplicates if row["artifact_type"] == "run" and row["arm"] == "control").update(
        result_state="fatal", failure_class="timeout"
    )
    failure = make_valid_record(load_schema(), "failure")
    for field in ("packet_id", "requirement_ids", "control_commit", "candidate_commit", "candidate_config_hash", "plan_sha256"):
        failure[field] = copy.deepcopy(gate[field])
    failure.update(status="complete", environment_id="macos-arm64-python-3.14", case_id="case-1", arm="control",
                   attempt=1, final_state="fatal")
    failed_with_duplicates.extend([failure, copy.deepcopy(failure)])
    with pytest.raises(ValueError, match="duplicate retained failure"):
        derive_gate_result(failed_with_duplicates, gate)


def test_retrieval_and_total_system_regressions_are_derived_from_raw_rows(tmp_path):
    _, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    case = next(row for row in rows if row["artifact_type"] == "case")
    case["gold_evidence"] = [{"kind": "interval", "start": 0.0, "end": 10.0}]
    case["explicit_flags"]["before_after_windows"] = [{"before": [0.0, 2.0], "after": [8.0, 10.0]}]
    for row in (row for row in rows if row["artifact_type"] == "retrieval"):
        row["selected_evidence"] = [
            {"kind": "interval", "start": 0.0, "end": 5.0},
            {"kind": "point", "time": 1.0}, {"kind": "point", "time": 9.0},
        ]
        row["temporal_iou"] = 0.5
        row["before_after_match"] = True
    candidate_usage = next(row for row in rows if row["artifact_type"] == "usage" and row["arm"] == "candidate")
    candidate_usage.update(dollars=1.0, all_model_input_tokens=100000, all_model_output_tokens=100000, calls=1000)
    derived = derive_gate_result(rows, gate)
    assert derived["aggregates"]["temporal_iou"]
    assert derived["aggregates"]["before_after"]["candidate_recall"] == 1.0
    assert any(item.startswith("total_system_dollars") for item in derived["aggregates"]["strict_regressions"])
    assert any(item.startswith("total_system_all_model_input_tokens") for item in derived["aggregates"]["strict_regressions"])
    assert any(item.startswith("total_system_all_model_output_tokens") for item in derived["aggregates"]["strict_regressions"])
    assert any(item.startswith("total_system_calls") for item in derived["aggregates"]["strict_regressions"])

    tampered = copy.deepcopy(rows)
    next(row for row in tampered if row["artifact_type"] == "retrieval")["temporal_iou"] = 1.0
    with pytest.raises(ValueError, match="temporal_iou"):
        derive_gate_result(tampered, gate)


def test_resource_coverage_is_required_for_failed_retry_attempts(tmp_path):
    schema, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    control_retry = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "run" and row["arm"] == "control"))
    candidate_retry = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "run" and row["arm"] == "candidate"))
    control_retry.update(attempt=2, result_state="fatal", failure_class="timeout")
    candidate_retry.update(attempt=2, result_state="success", failure_class=None)
    rows.extend([control_retry, candidate_retry])
    for arm in ("control", "candidate"):
        usage = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "usage" and row["arm"] == arm))
        usage["attempt"] = 2
        rows.append(usage)
    failure = make_valid_record(schema, "failure")
    for field in ("packet_id", "requirement_ids", "control_commit", "candidate_commit", "candidate_config_hash", "plan_sha256"):
        failure[field] = copy.deepcopy(gate[field])
    failure.update(status="complete", environment_id="macos-arm64-python-3.14", case_id="case-1", arm="control",
                   attempt=2, final_state="fatal")
    rows.append(failure)
    with pytest.raises(ValueError, match="resource evidence must cover every run attempt"):
        derive_gate_result(rows, gate)


@pytest.mark.parametrize("retry_arm", ["candidate", "control"])
def test_asymmetric_retry_retains_its_own_work_without_fictitious_partner(tmp_path, retry_arm):
    schema, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    retry = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "run" and row["arm"] == retry_arm))
    retry.update(attempt=2, order=1, result_state="fatal", failure_class="timeout")
    rows.append(retry)
    usage = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "usage" and row["arm"] == retry_arm))
    usage["attempt"] = 2
    rows.append(usage)
    failure = make_valid_record(schema, "failure")
    for field in ("packet_id", "requirement_ids", "control_commit", "candidate_commit", "candidate_config_hash", "plan_sha256"):
        failure[field] = copy.deepcopy(gate[field])
    failure.update(status="complete", environment_id="macos-arm64-python-3.14", case_id="case-1", arm=retry_arm,
                   attempt=2, final_state="fatal")
    rows.append(failure)
    for state in ("cold", "warm"):
        resource = copy.deepcopy(next(row for row in rows if row["artifact_type"] == "resource" and row["arm"] == retry_arm and row["state"] == state))
        resource.update(attempt=2, repeat_id=f"{state}-retry-{retry_arm}", pair_id=None)
        rows.append(resource)
    derived = derive_gate_result(rows, gate)
    assert derived["aggregates"]["attempt_accounting"]["attempts"] == 3
    assert derived["aggregates"]["attempt_accounting"]["failed_attempts"] == 1


def test_paired_initial_order_is_hash_bound_and_retry_order_is_not_paired(tmp_path):
    _, gate, _ = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    runs = [row for row in rows if row["artifact_type"] == "run"]
    assert {row["order"] for row in runs} == {1, 2}
    swapped = copy.deepcopy(rows)
    for row in (row for row in swapped if row["artifact_type"] == "run"):
        row["order"] = 3 - row["order"]
    with pytest.raises(ValueError, match="deterministic paired order"):
        derive_gate_result(swapped, gate)
    duplicate = copy.deepcopy(rows)
    for row in (row for row in duplicate if row["artifact_type"] == "run"):
        row["order"] = 1
    with pytest.raises(ValueError, match="unique orders"):
        derive_gate_result(duplicate, gate)
    wrong = copy.deepcopy(rows)
    next(row for row in wrong if row["artifact_type"] == "run" and row["arm"] == "candidate")["order"] = 3
    with pytest.raises(ValueError, match="order must be 1 or 2"):
        derive_gate_result(wrong, gate)


def test_confirmatory_one_family_cannot_self_declare_power(tmp_path):
    _, gate, gate_path = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    gate.update(evaluation_split="confirmatory", minimum_confirmatory_families=1,
                minimum_confirmatory_families_by_class={"targeted": 1})
    for row in rows:
        if row["artifact_type"] == "case":
            row["split"] = "confirmatory"
    with pytest.raises(ValueError, match="underpowered confirmatory"):
        derive_gate_result(rows, gate)


def test_unknown_ids_malformed_complete_case_and_provenance_are_rejected(tmp_path):
    schema = load_schema()
    case = make_valid_record(schema, "case")
    case.update(packet_id="P999", requirement_ids=["FAKE-001"], environment_id="moon-python",
                status="complete", gold_evidence=None, gold_unavailable_reason=None, obligations=[])
    errors = validate_record(case, schema)
    assert any("unknown packet_id" in error for error in errors)
    assert any("unknown requirement_id" in error for error in errors)
    assert any("invalid enum" in error for error in errors)
    assert any("null gold_evidence" in error for error in errors)
    assert any("at least one obligation" in error for error in errors)

    _, gate, gate_path = _canonical_gate_fixture(tmp_path)
    usage = tmp_path / "usage.jsonl"
    rows = [json.loads(line) for line in usage.read_text().splitlines()]
    rows[0]["candidate_commit"] = "f" * 40
    usage.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    gate["raw_input_checksums"]["usage.jsonl"] = hashlib.sha256(usage.read_bytes()).hexdigest()
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    assert any("inconsistent provenance" in error for error in validate_evidence_set([gate_path], schema))


def test_unrelated_raw_input_is_rejected_even_with_valid_checksum(tmp_path):
    schema, gate, gate_path = _canonical_gate_fixture(tmp_path)
    unrelated = tmp_path / "summary.json"
    unrelated.write_text("{}", encoding="utf-8")
    gate["raw_inputs"].append("summary.json")
    gate["raw_input_checksums"]["summary.json"] = hashlib.sha256(unrelated.read_bytes()).hexdigest()
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    assert any("unrelated raw input" in error for error in validate_evidence_set([gate_path], schema))


def test_asr_rows_must_reference_canonical_cases(tmp_path):
    _, gate, gate_path = _canonical_gate_fixture(tmp_path)
    rows = []
    for name in gate["raw_inputs"]:
        rows.extend(json.loads(line) for line in (tmp_path / name).read_text().splitlines() if line)
    schema = load_schema()
    ghost = make_valid_record(schema, "asr")
    for field in ("packet_id", "requirement_ids", "control_commit", "candidate_commit",
                  "candidate_config_hash", "plan_sha256"):
        ghost[field] = copy.deepcopy(gate[field])
    ghost.update(status="complete", case_id="ghost", environment_id="macos-arm64-python-3.14")
    with pytest.raises(ValueError, match="unrelated case"):
        derive_gate_result([*rows, ghost], {**gate, "asr_applicable": True})
