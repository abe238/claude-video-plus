#!/usr/bin/env python3
"""Preflight the sealed development slice without admitting reserve identities.

The real manifest is deliberately ``tools/development-manifest.local.json`` and is
ignored.  This adapter only translates its pre-registered mappings into P01/P02
inputs. Both arms intentionally use the Control-compatible configuration, so this proves corpus
and acquisition conformance only; it neither runs evidence mode, grades answers, nor derives
performance claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import control_conformance, control_harness, corpus_registry


class DevelopmentRunnerRefusal(RuntimeError):
    """A development benchmark precondition failed before an arm could run."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentRunnerRefusal(f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise DevelopmentRunnerRefusal(f"{label} must be a JSON object")
    return value


def _development_identities(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    errors = corpus_registry.validate_registry(registry)
    if errors:
        raise DevelopmentRunnerRefusal("invalid sealed registry")
    return {
        identity["identity_id"]: {"family_id": family["family_id"], "identity_sha256": identity["identity_sha256"],
                                  "question_classes": set(family["question_classes"])}
        for family in registry["families"] if family["split"] == "development"
        for identity in family["identities"]
    }


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise DevelopmentRunnerRefusal(f"{label} must be a lowercase SHA-256")
    return value


def _case_id(identity_id: str, question: str) -> str:
    return "dev-" + _sha256_bytes((identity_id + "\0" + question).encode("utf-8"))[:20]


def _source_kind_and_hash(source: Any) -> tuple[str, str]:
    """Validate a local file or public HTTP(S) locator without persisting it."""
    if not isinstance(source, str) or not source:
        raise DevelopmentRunnerRefusal("development source is required")
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "url", _sha256_bytes(source.encode("utf-8"))
    path = Path(source)
    if not path.is_absolute() or not path.is_file():
        raise DevelopmentRunnerRefusal("development local source must be an existing absolute file")
    return "local", _sha256_bytes(path.read_bytes())


def _validate_manifest(manifest: dict[str, Any], registry: dict[str, Any], *, repo: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    required = {"schema_version", "actor_id", "registry_seal_sha256", "candidate_commit", "candidate_config_path",
                "candidate_config_sha256", "environment", "cases"}
    if set(manifest) != required or manifest.get("schema_version") != 1:
        raise DevelopmentRunnerRefusal("local manifest has an unsupported schema")
    identities = _development_identities(registry)
    frozen = registry["frozen"]
    if manifest["actor_id"] not in registry["development_executor_ids"]:
        raise DevelopmentRunnerRefusal("manifest actor is not a development executor")
    if manifest["registry_seal_sha256"] != registry["seal_sha256"]:
        raise DevelopmentRunnerRefusal("local manifest registry seal does not match")
    if manifest["candidate_commit"] != frozen["candidate_commit"]:
        raise DevelopmentRunnerRefusal("local manifest candidate commit does not match frozen registry")
    config_hash = _require_sha(manifest["candidate_config_sha256"], "candidate_config_sha256")
    if config_hash != frozen["candidate_config_hash"]:
        raise DevelopmentRunnerRefusal("local manifest candidate config does not match frozen registry")
    config_path = Path(manifest["candidate_config_path"])
    if not config_path.is_absolute() or not config_path.is_file() or _sha256_bytes(config_path.read_bytes()) != config_hash:
        raise DevelopmentRunnerRefusal("candidate config path/hash drifted")
    environment = manifest["environment"]
    if not isinstance(environment, dict) or set(environment) != {"environment_id", "tools", "locale", "network_policy", "timeout_seconds", "retry_policy"}:
        raise DevelopmentRunnerRefusal("local manifest environment is incomplete")
    if environment["environment_id"] not in frozen["supported_environments"]:
        raise DevelopmentRunnerRefusal("environment is not frozen for this registry")
    if environment["retry_policy"] != {"harness_attempts": 1}:
        raise DevelopmentRunnerRefusal("retry policy must pin one harness attempt")
    if not isinstance(manifest["cases"], list) or not manifest["cases"]:
        raise DevelopmentRunnerRefusal("local manifest requires development cases")
    seen: set[str] = set()
    for item in manifest["cases"]:
        if not isinstance(item, dict) or set(item) != {"identity_id", "source", "caption_sha256", "question", "question_class", "frozen_flags", "obligations", "gold_evidence", "gold_unavailable_reason", "reader"}:
            raise DevelopmentRunnerRefusal("local manifest case is incomplete")
        identity_id = item["identity_id"]
        if identity_id not in identities:  # includes every confirmatory identity, without exposing one
            raise DevelopmentRunnerRefusal("case identity is not an authorized development identity")
        if identity_id in seen:
            raise DevelopmentRunnerRefusal("local manifest repeats a development identity")
        seen.add(identity_id)
        if item["question_class"] not in identities[identity_id]["question_classes"] or item["question_class"] not in frozen["supported_classes"]:
            raise DevelopmentRunnerRefusal("case question class is not registered for its identity")
        if not isinstance(item["question"], str) or not item["question"].strip():
            raise DevelopmentRunnerRefusal("case requires a fixed non-empty question")
        if not isinstance(item["obligations"], list) or not item["obligations"] or not all(isinstance(value, str) and value for value in item["obligations"]):
            raise DevelopmentRunnerRefusal("case requires non-empty gold obligations")
        gold, reason = item["gold_evidence"], item["gold_unavailable_reason"]
        if (gold is None) == (reason is None) or (gold is not None and not isinstance(gold, list)) or (reason is not None and (not isinstance(reason, str) or not reason)):
            raise DevelopmentRunnerRefusal("case must declare gold evidence or an unavailable reason")
        source_kind, source_hash = _source_kind_and_hash(item["source"])
        if source_kind == "url" and environment["network_policy"] != "enabled":
            raise DevelopmentRunnerRefusal("public URL source requires enabled network policy")
        caption_hash = item["caption_sha256"]
        if source_kind == "url":
            _require_sha(caption_hash, "caption_sha256")
        elif caption_hash is not None:
            raise DevelopmentRunnerRefusal("local source caption_sha256 must be null")
        if source_hash != identities[identity_id]["identity_sha256"]:
            raise DevelopmentRunnerRefusal("development source identity hash drifted")
    return environment, identities


def _build_case(item: dict[str, Any], identity: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    tools = environment["tools"]
    versions = control_harness.capture_tool_versions(tools)
    hashes = control_harness.capture_tool_sha256(tools)
    source_kind, _ = _source_kind_and_hash(item["source"])
    return {
        "schema_version": 1, "case_id": _case_id(item["identity_id"], item["question"]), "source": item["source"], "question": item["question"],
        "source_identity": {"kind": source_kind, "identity_sha256": identity["identity_sha256"], "caption_sha256": item["caption_sha256"]},
        "frozen_flags": item["frozen_flags"],
        "environment": {"tools": tools, "tool_versions": versions, "tool_sha256": hashes, "os": platform.system(),
                        "architecture": platform.machine(), "locale": environment["locale"], "network_policy": environment["network_policy"],
                        "cookie_input_policy": "none", "timeout_seconds": environment["timeout_seconds"], "invocation_policy": environment["retry_policy"]},
        "reader": item["reader"],
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def run(manifest_path: Path, registry_path: Path, *, repo: Path, control_worktree: Path, output_root: Path,
        run_pair: Callable[..., dict[str, Any]] = control_conformance.run_pair) -> dict[str, Any]:
    """Execute one Control-compatible P02 preflight per development mapping."""
    repo, output_root = repo.resolve(), output_root.resolve()
    try:
        output_root.relative_to(repo)
    except ValueError:
        pass
    else:
        raise DevelopmentRunnerRefusal("output root must be outside the repository")
    if output_root.exists() and any(output_root.iterdir()):
        raise DevelopmentRunnerRefusal("development output root must be empty")
    manifest, registry = _load_json(manifest_path, "local manifest"), _load_json(registry_path, "registry")
    environment, identities = _validate_manifest(manifest, registry, repo=repo)
    control_harness.assert_clean_detached_control(control_worktree, control_harness.CONTROL_COMMIT)
    candidate = control_conformance.candidate_identity(repo, repo)
    if candidate["candidate_commit"] != registry["frozen"]["candidate_commit"]:
        raise DevelopmentRunnerRefusal("current candidate commit does not match frozen registry")
    output_root.mkdir(parents=True)
    provenance = {"schema_version": 1, "registry_seal_sha256": registry["seal_sha256"], "candidate": candidate,
                  "candidate_config_sha256": manifest["candidate_config_sha256"], "environment": {**environment, "tools": dict(environment["tools"])},
                  "timeout_retry_policy": {"timeout_seconds": environment["timeout_seconds"], "retry_policy": environment["retry_policy"]},
                  "output_root": str(output_root), "control_worktree": str(control_worktree.resolve()), "case_count": len(manifest["cases"])}
    (output_root / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    case_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    for item in manifest["cases"]:
        case = _build_case(item, identities[item["identity_id"]], environment)
        artifact_root = output_root / "artifacts" / case["case_id"]
        result = run_pair(case, repo=repo, control_worktree=control_worktree, candidate_root=repo, artifact_root=artifact_root)
        source_metadata_hash = _canonical_hash({"identity_id": item["identity_id"], "identity_sha256": identities[item["identity_id"]]["identity_sha256"]})
        case_rows.append({"schema_version": 1, "artifact_type": "case", "case_id": case["case_id"], "source_family_id": identities[item["identity_id"]]["family_id"], "split": "development", "question_class": item["question_class"], "source_metadata_hash": source_metadata_hash, "explicit_flags": item["frozen_flags"], "obligations": item["obligations"], "gold_evidence": item["gold_evidence"], "gold_unavailable_reason": item["gold_unavailable_reason"]})
        for arm in ("control", "candidate"):
            observed = result["arms"][arm]
            state = "success" if observed["exit_class"] == "success" else "fatal"
            run_rows.append({"schema_version": 1, "artifact_type": "run", "case_id": case["case_id"], "arm": arm, "attempt": 1, "order": result["paired_order"].index(arm) + 1, "configuration": {"control_commit": result["control_commit"], "candidate": result["candidate"], "flags": item["frozen_flags"], "tool_paths": environment["tools"], "tool_versions": control_harness.capture_tool_versions(environment["tools"]), "timeout_retry_policy": provenance["timeout_retry_policy"]}, "started_at_utc": _utc_now(), "ended_at_utc": _utc_now(), "result_state": state, "failure_class": None if state == "success" else observed["exit_class"], "raw_manifest_path": (Path("artifacts") / case["case_id"] / "conformance.json").as_posix()})
    _write_jsonl(output_root / "cases.jsonl", case_rows)
    _write_jsonl(output_root / "runs.jsonl", run_rows)
    return {"cases": len(case_rows), "runs": len(run_rows), "output_root": str(output_root)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("tools/development-manifest.local.json"))
    parser.add_argument("--registry", type=Path, default=Path("docs/execution/v1/CORPUS-REGISTRY-v1.json"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--control-worktree", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.manifest, args.registry, repo=args.repo, control_worktree=args.control_worktree, output_root=args.output_root), sort_keys=True))
    except (DevelopmentRunnerRefusal, control_harness.ControlIntegrityError, control_conformance.ConformanceRefusal) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
