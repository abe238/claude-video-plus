#!/usr/bin/env python3
"""Validate v1 evidence JSON/JSONL against the machine-readable schema registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from tools.evaluate_v1 import (
        MIN_CONFIRMATORY_FAMILIES,
        MIN_CONFIRMATORY_FAMILIES_PER_CLASS,
        derive_gate_result,
    )
except ModuleNotFoundError:  # direct `python3 tools/validate_v1_evidence.py ...`
    from evaluate_v1 import (  # type: ignore[no-redef]
        MIN_CONFIRMATORY_FAMILIES,
        MIN_CONFIRMATORY_FAMILIES_PER_CLASS,
        derive_gate_result,
    )


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/execution/v1/evidence-schema-v1.json"
TYPE_MAP = {
    "string": str, "integer": int, "number": (int, float), "boolean": bool,
    "array": list, "object": dict, "null": type(None),
}
PATTERNS = {
    "sha40": re.compile(r"^[0-9a-f]{40}$"),
    "sha64": re.compile(r"^[0-9a-f]{64}$"),
    "packet_id": re.compile(r"^P[0-9]+[A-Z]?$"),
    "utc_timestamp": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"),
}
NONNEGATIVE_FIELDS = {
    "attempt", "order", "citations_checked", "reader_text_tokens", "reader_image_tokens",
    "all_model_input_tokens", "all_model_output_tokens", "calls", "dollars", "wall_ms",
    "cpu_ms", "peak_rss_bytes", "disk_bytes", "network_bytes", "process_calls",
    "initialization_ms", "exit_code", "duration_ms", "artifact_bytes", "observed_matches",
    "bootstrap_seed", "minimum_confirmatory_families", "substitutions", "deletions",
    "insertions", "reference_words",
}
POSITIVE_FIELDS = {"attempt", "order", "minimum_confirmatory_families", "reference_words"}
PATH_FIELDS = {"raw_manifest_path", "artifact_path"}


def _registry_ids() -> tuple[set[str], dict[str, str]]:
    registry = json.loads((ROOT / "docs/execution/v1/REQUIREMENTS.json").read_text(encoding="utf-8"))
    packets = {packet["id"] for packet in registry["packets"]}
    requirements = {item["id"]: item["packet"] for item in registry["requirements"]}
    return packets, requirements


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(value: Any, names: list[str]) -> bool:
    for name in names:
        expected = TYPE_MAP[name]
        if name == "integer" and isinstance(value, bool):
            continue
        if name == "number" and isinstance(value, bool):
            continue
        if isinstance(value, expected):
            return True
    return False


def _positive_denominator_tree(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value >= 0
    if isinstance(value, dict):
        return bool(value) and all(_positive_denominator_tree(item) for item in value.values())
    return False


def validate_record(record: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != schema["schema_version"]:
        errors.append("unknown schema_version")
    artifact_type = record.get("artifact_type")
    artifact = schema["artifacts"].get(artifact_type)
    if artifact is None:
        return [f"unknown artifact_type {artifact_type!r}"]
    fields = {**schema["common_fields"], **artifact.get("fields", {})}
    required = [*schema["common_required"], *artifact.get("required", [])]
    packets, requirements = _registry_ids()
    for name in required:
        if name not in record:
            errors.append(f"missing required field {name}")
    for name, value in record.items():
        spec = fields.get(name)
        if spec is None:
            continue
        if not _type_ok(value, spec["types"]):
            errors.append(f"{name} has wrong type")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name} has invalid enum value {value!r}")
        if value is not None and "enum_from" in spec and value not in schema[spec["enum_from"]]:
            errors.append(f"{name} has invalid enum value {value!r}")
        if value is not None and "pattern" in spec and isinstance(value, str):
            if not PATTERNS[spec["pattern"]].fullmatch(value):
                errors.append(f"{name} does not match {spec['pattern']}")
        if isinstance(value, list):
            if len(value) < int(spec.get("min_items", 0)):
                errors.append(f"{name} has too few items")
            item_type = spec.get("items")
            if item_type and any(not _type_ok(item, [item_type]) for item in value):
                errors.append(f"{name} has invalid item type")
    packet_id = record.get("packet_id")
    if packet_id not in packets:
        errors.append(f"unknown packet_id {packet_id!r}")
    requirement_ids = record.get("requirement_ids")
    if isinstance(requirement_ids, list):
        for requirement_id in requirement_ids:
            if requirement_id not in requirements:
                errors.append(f"unknown requirement_id {requirement_id!r}")
            elif requirements[requirement_id] != packet_id:
                errors.append(f"requirement_id {requirement_id!r} does not belong to packet {packet_id!r}")
    if record.get("status") != "provisional":
        for name in ("control_commit", "candidate_commit", "plan_sha256"):
            if record.get(name) is None:
                errors.append(f"{name} may be null only for provisional evidence")
        if record.get("candidate_config_hash") is None:
            errors.append("candidate_config_hash may be null only for provisional evidence")
    for name in NONNEGATIVE_FIELDS:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < 0 or (name in POSITIVE_FIELDS and value < 1):
                errors.append(f"{name} is outside its allowed range")
    for name in PATH_FIELDS:
        value = record.get(name)
        if isinstance(value, str) and (Path(value).is_absolute() or ".." in Path(value).parts):
            errors.append(f"{name} must be a safe relative path")
    if artifact_type == "run":
        state = record.get("result_state")
        failure = record.get("failure_class")
        if state in {"fatal", "unavailable", "partial"} and not failure:
            errors.append("non-success run requires failure_class")
        if state == "success" and failure is not None:
            errors.append("successful run must have null failure_class")
    if artifact_type == "case" and record.get("status") == "complete":
        if not str(record.get("case_id", "")).strip() or not str(record.get("source_family_id", "")).strip():
            errors.append("complete case requires non-empty case and source-family IDs")
        if not record.get("obligations"):
            errors.append("complete case requires at least one obligation")
        gold = record.get("gold_evidence")
        reason = record.get("gold_unavailable_reason")
        if gold is None and not (isinstance(reason, str) and reason.strip()):
            errors.append("complete case with null gold_evidence requires gold_unavailable_reason")
        if gold is not None and reason is not None:
            errors.append("case with gold_evidence must have null gold_unavailable_reason")
        if isinstance(gold, list):
            for item in gold:
                if not isinstance(item, dict) or item.get("kind") not in {"point", "interval"}:
                    errors.append("gold_evidence items must be point or interval objects")
                    continue
                if item["kind"] == "point" and not isinstance(item.get("time"), (int, float)):
                    errors.append("gold point requires numeric time")
                if item["kind"] == "interval" and not (
                    isinstance(item.get("start"), (int, float))
                    and isinstance(item.get("end"), (int, float))
                    and item["end"] > item["start"]
                ):
                    errors.append("gold interval requires numeric start < end")
    if artifact_type == "judgment" and not record.get("refused", False):
        scores = record.get("scores")
        required_scores = {"correctness", "completeness", "citation", "adherence"}
        if not isinstance(scores, dict) or set(scores) != required_scores or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10
            for value in scores.values()
        ):
            errors.append("judgment scores must be the four integer rubric values from 0 to 10")
    if artifact_type == "usage":
        source = record.get("measurement_source", "")
        if record.get("measurement_kind") == "reported" and not source.startswith("provider:"):
            errors.append("reported usage requires a provider measurement_source")
        if record.get("measurement_kind") == "estimated" and source.startswith("provider:"):
            errors.append("estimated usage cannot claim a provider-reported source")
    if artifact_type == "asr":
        if record.get("reference_words", 0) <= 0:
            errors.append("ASR reference_words must be positive")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
               for value in record.get("boundary_errors_seconds", [])):
            errors.append("ASR boundary errors must be finite non-negative numbers")
    if artifact_type == "gate_result":
        denominators = record.get("denominators")
        gates = record.get("gates")
        if not isinstance(denominators, dict) or not denominators or not _positive_denominator_tree(denominators):
            errors.append("gate_result requires non-empty positive denominators (zero leaves allowed)")
        if not isinstance(gates, dict) or not gates or any(not isinstance(value, bool) for value in gates.values()):
            errors.append("gate_result requires non-empty boolean gates")
        if record.get("status") != "complete":
            errors.append("gate_result must have complete status")
        if record.get("evaluation_split") == "confirmatory":
            if record.get("minimum_confirmatory_families", 0) < MIN_CONFIRMATORY_FAMILIES:
                errors.append(f"confirmatory minimum must be at least {MIN_CONFIRMATORY_FAMILIES} families")
            minima = record.get("minimum_confirmatory_families_by_class", {})
            for name in record.get("required_classes", []):
                if not isinstance(minima.get(name), int) or minima[name] < MIN_CONFIRMATORY_FAMILIES_PER_CLASS:
                    errors.append(
                        f"confirmatory class {name!r} minimum must be at least "
                        f"{MIN_CONFIRMATORY_FAMILIES_PER_CLASS} families"
                    )
        for value in record.get("raw_inputs", []):
            if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
                errors.append("raw_inputs must contain safe relative paths")
        required_classes = set(record.get("required_classes", []))
        covered_classes = set(record.get("covered_classes", []))
        required_environments = set(record.get("required_environments", []))
        covered_environments = set(record.get("covered_environments", []))
        if not required_classes.issubset(covered_classes):
            errors.append("gate_result does not cover every required class")
        if not required_environments.issubset(covered_environments):
            errors.append("gate_result does not cover every required environment")
        known_environments = set(schema["environment_ids"])
        for environment in required_environments | covered_environments:
            if environment not in known_environments:
                errors.append(f"gate_result references unknown environment {environment!r}")
    return errors


def _load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(path.read_text(encoding="utf-8"))]


def validate_evidence_set(paths: list[Path], schema: dict[str, Any]) -> list[str]:
    """Validate records plus cross-file pairing, identity, and referenced inputs."""
    errors: list[str] = []
    records: list[tuple[Path, int, dict[str, Any]]] = []
    for path in paths:
        try:
            loaded = _load_records(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: cannot load evidence: {exc}")
            continue
        for index, record in enumerate(loaded, start=1):
            records.append((path, index, record))
            errors.extend(
                f"{path}: record {index}: {error}"
                for error in validate_record(record, schema)
            )

    run_keys: set[tuple[Any, Any, Any]] = set()
    run_arms: dict[Any, set[Any]] = {}
    run_attempts: dict[tuple[Any, Any], set[int]] = {}
    family_splits: dict[Any, set[Any]] = {}
    for path, index, record in records:
        kind = record.get("artifact_type")
        if kind == "case":
            family_splits.setdefault(record.get("source_family_id"), set()).add(record.get("split"))
        if kind == "run":
            key = (record.get("case_id"), record.get("arm"), record.get("attempt"))
            if key in run_keys:
                errors.append(f"{path}: record {index}: duplicate case/arm/attempt {key}")
            run_keys.add(key)
            run_arms.setdefault(record.get("case_id"), set()).add(record.get("arm"))
            if isinstance(record.get("attempt"), int):
                run_attempts.setdefault((record.get("case_id"), record.get("arm")), set()).add(record["attempt"])
            relative = record.get("raw_manifest_path")
            if isinstance(relative, str) and not Path(relative).is_absolute() and ".." not in Path(relative).parts:
                if not (path.parent / relative).is_file():
                    errors.append(f"{path}: record {index}: raw_manifest_path does not exist")
        if kind == "gate_result":
            checksums = record.get("raw_input_checksums", {})
            canonical = schema["canonical_raw_artifacts"]
            seen_names: set[str] = set()
            raw_records: list[dict[str, Any]] = []
            for relative in record.get("raw_inputs", []):
                if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
                    errors.append(f"{path}: record {index}: raw_inputs must be safe relative paths")
                elif not (path.parent / relative).is_file():
                    errors.append(f"{path}: record {index}: raw input does not exist: {relative}")
                else:
                    name = Path(relative).name
                    if name not in canonical:
                        errors.append(f"{path}: record {index}: unrelated raw input: {relative}")
                        continue
                    if name in seen_names:
                        errors.append(f"{path}: record {index}: duplicate canonical raw input: {name}")
                        continue
                    seen_names.add(name)
                    expected = checksums.get(relative) if isinstance(checksums, dict) else None
                    observed = hashlib.sha256((path.parent / relative).read_bytes()).hexdigest()
                    if expected != observed:
                        errors.append(f"{path}: record {index}: raw input checksum mismatch: {relative}")
                    try:
                        linked = _load_records(path.parent / relative)
                    except (OSError, json.JSONDecodeError) as exc:
                        errors.append(f"{path}: record {index}: cannot load raw input {relative}: {exc}")
                        continue
                    for raw_index, raw in enumerate(linked, start=1):
                        if raw.get("artifact_type") != canonical[name]:
                            errors.append(
                                f"{path}: record {index}: {relative} record {raw_index} has non-canonical "
                                f"artifact_type {raw.get('artifact_type')!r}"
                            )
                        for error in validate_record(raw, schema):
                            errors.append(f"{path}: record {index}: {relative} record {raw_index}: {error}")
                        frozen = ("packet_id", "control_commit", "candidate_commit",
                                  "candidate_config_hash", "plan_sha256")
                        if any(raw.get(field) != record.get(field) for field in frozen) or set(
                            raw.get("requirement_ids", [])
                        ) != set(record.get("requirement_ids", [])):
                            errors.append(
                                f"{path}: record {index}: inconsistent provenance in {relative} record {raw_index}"
                            )
                        if raw.get("status") != "complete":
                            errors.append(
                                f"{path}: record {index}: gate raw input is not complete: {relative} record {raw_index}"
                            )
                    raw_records.extend(linked)
            if isinstance(checksums, dict) and set(checksums) != set(record.get("raw_inputs", [])):
                errors.append(f"{path}: record {index}: raw_input_checksums keys must exactly match raw_inputs")
            required_names = {
                "cases.jsonl", "runs.jsonl", "judgments.jsonl", "retrieval.jsonl",
                "usage.jsonl", "resources.jsonl", "failures.jsonl",
            }
            if record.get("asr_applicable"):
                required_names.add("asr.jsonl")
            if record.get("gate_scope") == "release":
                required_names.update({"install-results.jsonl", "privacy-scan.jsonl", "provenance.jsonl"})
            missing = required_names - seen_names
            if missing:
                errors.append(
                    f"{path}: record {index}: gate is missing canonical raw inputs: {sorted(missing)}"
                )
            if not missing and raw_records:
                try:
                    recomputed = derive_gate_result(raw_records, record)
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                    errors.append(f"{path}: record {index}: cannot derive gate from canonical raw inputs: {exc}")
                else:
                    for field in ("denominators", "aggregates", "gates", "pareto_promote",
                                  "covered_classes", "covered_environments"):
                        if record.get(field) != recomputed[field]:
                            errors.append(
                                f"{path}: record {index}: self-asserted {field} does not match canonical raw inputs"
                            )

    for case_id, arms in run_arms.items():
        if arms != {"control", "candidate"}:
            errors.append(f"case {case_id!r} lacks paired control/candidate runs")
    for key, attempts in run_attempts.items():
        if attempts and attempts != set(range(1, max(attempts) + 1)):
            errors.append(f"case/arm {key!r} has a dropped attempt")
    for family, splits in family_splits.items():
        if "development" in splits and "confirmatory" in splits:
            errors.append(f"source family {family!r} leaks across development and confirmatory")

    # Repository evidence must live in the directory owned by its packet.
    registry_path = ROOT / "docs/execution/v1/REQUIREMENTS.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        owned = {packet["id"]: (ROOT / packet["evidence"]).resolve() for packet in registry["packets"]}
        for path, index, record in records:
            try:
                resolved = path.resolve()
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                continue
            packet_root = owned.get(record.get("packet_id"))
            if packet_root is None or (resolved != packet_root and packet_root not in resolved.parents):
                errors.append(f"{path}: record {index}: evidence path is outside packet-owned directory")
    return errors


def validate_path(path: Path, schema: dict[str, Any]) -> list[str]:
    records = _load_records(path)
    errors = []
    for index, record in enumerate(records, start=1):
        errors.extend(f"record {index}: {error}" for error in validate_record(record, schema))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    schema = load_schema()
    errors = validate_evidence_set(args.paths, schema)
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print(f"ok: {len(args.paths)} evidence file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
