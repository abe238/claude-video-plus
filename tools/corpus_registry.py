#!/usr/bin/env python3
"""Validate the v1 development/confirmatory corpus seal and its access journal.

The registry deliberately stores synthetic opaque identities, never source locators.  The
custodian keeps the mapping to any real source outside this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REGISTRY_VERSION = "corpus-registry-v1"
GENESIS_HASH = "0" * 64
MIN_FAMILIES = 5
MIN_FAMILIES_PER_CLASS = 3
_FROZEN_KEYS = {
    "candidate_commit", "candidate_config_hash", "routing_epoch", "prompt_epoch", "reader_epoch",
    "grader_epoch", "evaluator_version", "exclusions", "supported_classes",
    "supported_environments", "minimum_confirmatory_families", "minimum_confirmatory_families_by_class",
}
_REGISTRY_KEYS = {"schema_version", "registry_version", "status", "custodian_id", "development_executor_ids", "frozen", "families", "seal_sha256"}
_FAMILY_KEYS = {"family_id", "split", "question_classes", "identities"}
_IDENTITY_KEYS = {"identity_id", "identity_sha256"}
_LABEL = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_ENVIRONMENT = re.compile(r"^(?:macos-arm64|ubuntu-x86_64)-python-[0-9]+\.[0-9]+$")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def registry_fingerprint(registry: dict[str, Any]) -> str:
    """Hash immutable registry content without its self-referential seal field."""
    payload = {key: value for key, value in registry.items() if key != "seal_sha256"}
    return _sha256(payload)


def frozen_epochs_fingerprint(registry: dict[str, Any]) -> str:
    return _sha256(registry.get("frozen", {}))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _identity_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        identity["identity_id"]: {"family": family, "identity": identity}
        for family in registry.get("families", [])
        for identity in family.get("identities", [])
        if isinstance(identity, dict) and isinstance(identity.get("identity_id"), str)
    }


def _label(value: Any) -> bool:
    return isinstance(value, str) and bool(_LABEL.fullmatch(value))


def validate_registry(registry: dict[str, Any]) -> list[str]:
    """Return deterministic integrity errors without reading real corpus material."""
    errors: list[str] = []
    if set(registry) != _REGISTRY_KEYS:
        errors.append("registry has unexpected or missing keys")
    if registry.get("schema_version") != 1:
        errors.append("registry schema_version must be 1")
    if registry.get("registry_version") != REGISTRY_VERSION:
        errors.append("unknown registry_version")
    if registry.get("status") != "sealed":
        errors.append("registry must be sealed before metric-changing work")
    if not _label(registry.get("custodian_id")):
        errors.append("registry custodian_id must be an opaque label")
    executors = registry.get("development_executor_ids")
    if not isinstance(executors, list) or not executors or any(not _label(item) for item in executors):
        errors.append("registry requires development executor IDs")
    if isinstance(executors, list) and len(set(executors)) != len(executors):
        errors.append("registry has duplicate development executor IDs")
    frozen = registry.get("frozen")
    if not isinstance(frozen, dict) or set(frozen) != _FROZEN_KEYS:
        errors.append("registry lacks frozen candidate/config/routing/prompt/epoch/cohort fields")
    else:
        if not isinstance(frozen["candidate_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", frozen["candidate_commit"]):
            errors.append("frozen candidate_commit must be a lowercase sha40")
        if not _is_sha256(frozen["candidate_config_hash"]):
            errors.append("frozen candidate_config_hash must be a sha256")
        if frozen["evaluator_version"] != "v1":
            errors.append("frozen evaluator_version must be v1")
        if not isinstance(frozen["exclusions"], list) or any(
            not isinstance(rule, str) or not re.fullmatch(r"mechanical:[a-z0-9]+(?:-[a-z0-9]+)*", rule)
            for rule in frozen["exclusions"]
        ):
            errors.append("exclusions must be preregistered mechanical opaque labels")
        elif any("outcome" in rule or "result" in rule for rule in frozen["exclusions"]):
            errors.append("outcome-aware exclusions are forbidden")
        for name in ("routing_epoch", "prompt_epoch", "reader_epoch", "grader_epoch"):
            if not _label(frozen[name]):
                errors.append(f"frozen {name} must be an opaque label")
        if not isinstance(frozen["supported_classes"], list) or not frozen["supported_classes"] or any(
            not _label(name) for name in frozen["supported_classes"]
        ):
            errors.append("supported classes must be opaque labels")
        if not isinstance(frozen["supported_environments"], list) or not frozen["supported_environments"] or any(
            not isinstance(name, str) or not _ENVIRONMENT.fullmatch(name) for name in frozen["supported_environments"]
        ):
            errors.append("supported environments must be known opaque environment labels")
        if int(frozen["minimum_confirmatory_families"]) < MIN_FAMILIES:
            errors.append("confirmatory minimum must be at least 5")
        minima = frozen["minimum_confirmatory_families_by_class"]
        if not isinstance(minima, dict) or any(
            not isinstance(minima.get(name), int) or minima[name] < MIN_FAMILIES_PER_CLASS
            for name in frozen["supported_classes"]
        ):
            errors.append("every supported class requires a confirmatory minimum of at least 3")
        if not frozen["supported_environments"]:
            errors.append("registry requires supported environments")
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    seen_families: set[str] = set()
    confirmatory_families: list[dict[str, Any]] = []
    for family in registry.get("families", []):
        if not isinstance(family, dict) or set(family) != _FAMILY_KEYS or family.get("split") not in {"development", "confirmatory"}:
            errors.append("every family must have one development or confirmatory split")
            continue
        family_id = family.get("family_id")
        if not _label(family_id):
            errors.append("family_id must be an opaque label")
        elif family_id in seen_families:
            errors.append(f"duplicate family assignment: {family_id}")
        seen_families.add(family_id)
        identities = family.get("identities")
        if not isinstance(identities, list) or not identities:
            errors.append(f"family {family_id!r} lacks identities")
            continue
        if family["split"] == "confirmatory":
            confirmatory_families.append(family)
        if not isinstance(family.get("question_classes"), list) or not family["question_classes"] or any(
            not _label(name) for name in family["question_classes"]
        ):
            errors.append("family question_classes must be opaque labels")
        for identity in identities:
            if not isinstance(identity, dict) or set(identity) != _IDENTITY_KEYS:
                errors.append("identity must be an object")
                continue
            identity_id, identity_hash = identity.get("identity_id"), identity.get("identity_sha256")
            if not _label(identity_id):
                errors.append("identity_id must be an opaque label")
            elif identity_id in seen_ids:
                errors.append(f"duplicate identity alias: {identity_id}")
            seen_ids.add(identity_id)
            if not _is_sha256(identity_hash):
                errors.append(f"identity {identity_id!r} requires sha256 placeholder")
            elif identity_hash in seen_hashes:
                errors.append(f"duplicate identity hash/alias: {identity_id}")
            seen_hashes.add(identity_hash)
    if isinstance(frozen, dict):
        if len(confirmatory_families) < int(frozen["minimum_confirmatory_families"]):
            errors.append("underpowered confirmatory cohort overall")
        for name in frozen["supported_classes"]:
            count = sum(name in family.get("question_classes", []) for family in confirmatory_families)
            if count < int(frozen["minimum_confirmatory_families_by_class"].get(name, 0)):
                errors.append(f"underpowered confirmatory cohort for class {name!r}")
    if registry.get("seal_sha256") != registry_fingerprint(registry):
        errors.append("seal_sha256 does not match immutable registry content (late reassignment or stale seal)")
    return errors


def visible_identities(registry: dict[str, Any], *, actor_id: str, split: str = "development") -> list[str]:
    """Return only development IDs to a named executor; reserve IDs never enter that view."""
    if validate_registry(registry):
        raise ValueError("invalid corpus registry")
    if actor_id not in registry["development_executor_ids"]:
        raise PermissionError("actor is not an authorized development executor")
    if split != "development":
        raise PermissionError("development executors cannot access confirmatory identities")
    return [
        identity["identity_id"] for family in registry["families"] if family["split"] == "development"
        for identity in family["identities"]
    ]


def _record_fingerprint(record: dict[str, Any]) -> str:
    return _sha256({key: value for key, value in record.items() if key != "record_hash"})


def build_access_record(
    registry: dict[str, Any], records: list[dict[str, Any]], *, actor_id: str, action: str,
    identity_ids: list[str], authorization_id: str,
) -> dict[str, Any]:
    """Make one append-only record. Callers persist it as one JSONL line without rewriting prior lines."""
    record = {
        "schema_version": 1,
        "registry_version": REGISTRY_VERSION,
        "sequence": len(records) + 1,
        "actor_id": actor_id,
        "action": action,
        "authorization_id": authorization_id,
        "identity_ids": list(identity_ids),
        "registry_seal_sha256": registry.get("seal_sha256"),
        "frozen_epochs_sha256": frozen_epochs_fingerprint(registry),
        "previous_hash": records[-1].get("record_hash", GENESIS_HASH) if records else GENESIS_HASH,
    }
    record["record_hash"] = _record_fingerprint(record)
    return record


def validate_access_log(registry: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    errors = validate_registry(registry)
    identities = _identity_map(registry)
    previous = GENESIS_HASH
    spent = False
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append(f"access record {position} is not an object")
            continue
        if record.get("sequence") != position:
            errors.append(f"access record {position} has non-append-only sequence")
        if record.get("previous_hash") != previous:
            errors.append(f"access record {position} previous_hash does not chain")
        if record.get("record_hash") != _record_fingerprint(record):
            errors.append(f"access record {position} record_hash does not verify")
        previous = record.get("record_hash", "")
        if record.get("registry_seal_sha256") != registry.get("seal_sha256"):
            errors.append(f"access record {position} has stale registry seal")
        if record.get("frozen_epochs_sha256") != frozen_epochs_fingerprint(registry):
            errors.append(f"access record {position} has stale frozen epochs")
        if record.get("actor_id") != registry.get("custodian_id"):
            errors.append(f"access record {position} requires custodian authorization")
        if record.get("action") not in {"authorized_open", "exposure"}:
            errors.append(f"access record {position} has unknown action")
        requested = record.get("identity_ids")
        if not isinstance(requested, list) or not requested:
            errors.append(f"access record {position} has no reserve identity")
        elif any(item not in identities or identities[item]["family"].get("split") != "confirmatory" for item in requested):
            errors.append(f"access record {position} references non-confirmatory identity")
        if not isinstance(record.get("authorization_id"), str) or not record["authorization_id"]:
            errors.append(f"access record {position} lacks authorization_id")
        if spent:
            errors.append(f"access record {position} reuses a spent cohort")
        if record.get("action") == "exposure":
            spent = True
    return errors


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", type=Path)
    parser.add_argument("--access-log", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    errors = validate_registry(registry)
    if args.access_log:
        errors.extend(validate_access_log(registry, _read_jsonl(args.access_log)))
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("ok: corpus registry seal and access log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
