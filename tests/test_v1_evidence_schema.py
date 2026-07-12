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
                selected_evidence=[{"kind": "point", "time": 1.0}])
            for arm in ("control", "candidate")
        ],
        "usage.jsonl": [
            row("usage", case_id="case-1", arm="control", reader_text_tokens=100,
                reader_image_tokens=0, all_model_input_tokens=100),
            row("usage", case_id="case-1", arm="candidate", reader_text_tokens=40,
                reader_image_tokens=0, all_model_input_tokens=40),
        ],
        "resources.jsonl": [
            row("resource", case_id="case-1", arm=arm, wall_ms=wall)
            for arm, wall in (("noop", 10.0), ("control", 100.0), ("candidate", 100.0))
            for _ in range(30)
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
