#!/usr/bin/env python3
"""Validate the v1 execution registry and its frozen-plan readiness."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "docs/execution/v1/REQUIREMENTS.json"
REQUIRED_SPECS = (
    "CONTROL.md",
    "MEASUREMENT.md",
    "CONTRACTS.md",
    "SUPPORT.md",
    "PROVENANCE.md",
    "EVIDENCE-SCHEMAS.md",
    "PROTOCOL.md",
    "CHAIN.md",
    "REQUIREMENT-CATALOG.md",
    "evidence-schema-v1.json",
)
NORMATIVE_PATHS = (
    "AGENTS.md",
    "docs/plans/V1.0-MASTER-PLAN.md",
    "docs/execution/v1/PROTOCOL.md",
    "docs/execution/v1/CHAIN.md",
    "docs/execution/v1/CONTROL.md",
    "docs/execution/v1/MEASUREMENT.md",
    "docs/execution/v1/CONTRACTS.md",
    "docs/execution/v1/SUPPORT.md",
    "docs/execution/v1/PROVENANCE.md",
    "docs/execution/v1/EVIDENCE-SCHEMAS.md",
    "docs/execution/v1/evidence-schema-v1.json",
    "docs/execution/v1/REQUIREMENT-CATALOG.md",
    "docs/execution/v1/REQUIREMENTS.json",
)
FINALIZER_PATHS = {
    "docs/execution/v1/REQUIREMENTS.json",
    "docs/evidence/v1/L0-plan-review/SOL-REVIEW.md",
    "docs/evidence/v1/L0-plan-review/verify.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def git_bytes(root: Path, *args: str) -> bytes:
    """Return Git output bytes without text-mode newline conversion."""
    return subprocess.run(
        ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def committed_file_matches(root: Path, commit: str, relative: str, current: Path) -> bool:
    """Compare a working file with its committed blob without newline conversion."""
    return git_bytes(root, "show", f"{commit}:{relative}") == current.read_bytes()


def committed_review_accepts_append(
    root: Path, commit: str, relative: str, current: Path, reviewed_tree: str,
) -> bool:
    """Validate an approval append against the byte-preserved committed review."""
    base = git_bytes(root, "show", f"{commit}:{relative}").decode("utf-8")
    candidate = current.read_bytes().decode("utf-8")
    return valid_approval_append(base, candidate, reviewed_tree)


def normative_manifest(root: Path, commit: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(NORMATIVE_PATHS):
        blob = subprocess.run(
            ["git", "show", f"{commit}:{path}"], cwd=root, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        digest.update(path.encode("utf-8") + b"\0" + blob + b"\0")
    return digest.hexdigest()


def github_issue(root: Path, repo: str, number: int) -> dict[str, Any] | None:
    try:
        output = subprocess.run(
            ["gh", "issue", "view", str(number), "--repo", repo, "--json", "title,state,url"],
            cwd=root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15,
        ).stdout
        return json.loads(output)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def valid_approval_append(base: str, current: str, reviewed_tree: str) -> bool:
    separator = "\n" if base.endswith("\n") else "\n\n"
    prefix = base + separator
    if not current.startswith(prefix):
        return False
    suffix = current[len(base):]
    pattern = (
        re.escape(separator) + r"## Final approval\n\nModel: `gpt-5\.6-sol`\n\n"
        r"Session: `([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`\n\n"
        rf"Approved staged tree: `{re.escape(reviewed_tree)}`\n\n"
        r"Final verdict: \*\*APPROVE\*\*\n?"
    )
    return re.fullmatch(pattern, suffix) is not None


def approval_session(base: str, current: str, reviewed_tree: str) -> str | None:
    if not valid_approval_append(base, current, reviewed_tree):
        return None
    match = re.search(
        r"Session: `([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`",
        current[len(base):],
    )
    return match.group(1) if match else None


def codex_session_approves(session: str, reviewed_tree: str) -> bool:
    candidates = list((Path.home() / ".codex/sessions").glob(f"**/*{session}.jsonl"))
    if len(candidates) != 1:
        return False
    assistant_messages: list[str] = []
    try:
        for line in candidates[0].read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            payload = event.get("payload", {})
            if event.get("type") != "response_item" or payload.get("role") != "assistant":
                continue
            blocks: list[str] = []
            for content in payload.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    blocks.append(str(content.get("text", "")))
            assistant_messages.append("".join(blocks))
    except (OSError, json.JSONDecodeError):
        return False
    final = assistant_messages[-1].strip() if assistant_messages else ""
    return final.startswith("APPROVE") and reviewed_tree in final


def strip_finalizer_fields(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)
    for field in (
        "status", "plan_commit", "plan_sha256", "approved_tree",
        "normative_manifest_sha256",
    ):
        normalized[field] = None
    review = normalized.get("sol_plan_review")
    if isinstance(review, dict):
        # Model and artifact path are semantic. Only the exact-tree review
        # outcome is a mechanical finalizer field.
        review["verdict"] = "__FINALIZED__"
        review["session"] = "__FINALIZED__"
        review["blocking"] = ["__FINALIZED__"]
        review["required"] = ["__FINALIZED__"]
    for requirement in normalized.get("requirements", []):
        if requirement.get("id") in {"GOV-001", "GOV-002", "GOV-003"}:
            requirement["status"] = "__FINALIZED__"
    for packet in normalized.get("packets", []):
        if packet.get("id") == "P00":
            packet["state"] = "__FINALIZED__"
            packet["sol_verdict"] = "__FINALIZED__"
            packet["commits"] = ["__FINALIZED__"]
    return normalized


def strip_verify_finalizer_fields(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)
    for field in (
        "status", "candidate_commit", "candidate_config_hash", "plan_sha256",
        "reviewed_tree", "artifact_checksums",
    ):
        normalized[field] = "__FINALIZED__"
    return normalized


def validate(data: dict[str, Any], *, root: Path = ROOT, ready: bool = False) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    github_repo = data.get("github_repo")
    if not isinstance(github_repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repo):
        errors.append("github_repo must be an owner/repository name")

    plan_rel = data.get("plan_path")
    plan_path = root / plan_rel if isinstance(plan_rel, str) else None
    if plan_path is None or not plan_path.is_file():
        errors.append("plan_path must name an existing file")

    spec_dir = root / "docs/execution/v1"
    for name in REQUIRED_SPECS:
        if not (spec_dir / name).is_file():
            errors.append(f"missing normative specification: {name}")

    packets = data.get("packets")
    requirements = data.get("requirements")
    if not isinstance(packets, list) or not packets:
        errors.append("packets must be a non-empty list")
        packets = []
    if not isinstance(requirements, list) or not requirements:
        errors.append("requirements must be a non-empty list")
        requirements = []

    packet_ids = [p.get("id") for p in packets if isinstance(p, dict)]
    requirement_ids = [r.get("id") for r in requirements if isinstance(r, dict)]
    for label, values in (("packet", packet_ids), ("requirement", requirement_ids)):
        if any(not isinstance(value, str) or not value for value in values):
            errors.append(f"every {label} must have a non-empty string id")
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            errors.append(f"duplicate {label} ids: {', '.join(duplicates)}")

    packet_set = set(packet_ids)
    for packet in packets:
        if not isinstance(packet, dict):
            errors.append("packet entries must be objects")
            continue
        for field in (
            "id", "loop", "title", "depends_on", "issue", "tests", "evidence",
            "sol_verdict", "commits", "disposition", "state",
        ):
            if field not in packet:
                errors.append(f"packet {packet.get('id')} missing {field}")
        dependencies = packet.get("depends_on", [])
        if not isinstance(dependencies, list):
            errors.append(f"packet {packet.get('id')} depends_on must be a list")
        else:
            unknown = sorted(set(dependencies) - packet_set)
            if unknown:
                errors.append(f"packet {packet.get('id')} has unknown dependencies: {unknown}")
            if packet.get("id") in dependencies:
                errors.append(f"packet {packet.get('id')} depends on itself")
        if not isinstance(packet.get("tests"), list) or not packet.get("tests"):
            errors.append(f"packet {packet.get('id')} tests must be a non-empty list")
        elif any(not isinstance(item, str) or not item.startswith("tests/") for item in packet["tests"]):
            errors.append(f"packet {packet.get('id')} tests must name repository test paths")
        if not isinstance(packet.get("evidence"), str) or not packet.get("evidence"):
            errors.append(f"packet {packet.get('id')} evidence must be a path")
        elif not packet["evidence"].startswith("docs/evidence/v1/"):
            errors.append(f"packet {packet.get('id')} evidence must stay under docs/evidence/v1")
        if not isinstance(packet.get("commits"), list):
            errors.append(f"packet {packet.get('id')} commits must be a list")
        if not isinstance(packet.get("issue"), int) or isinstance(packet.get("issue"), bool) or packet.get("issue", 0) < 1:
            errors.append(f"packet {packet.get('id')} issue must be a positive GitHub issue number")
        if packet.get("disposition") not in {"ship", "evaluate-only", "defer", "exclude"}:
            errors.append(f"packet {packet.get('id')} has invalid disposition")
        if packet.get("state") == "complete":
            missing_tests = [path for path in packet.get("tests", []) if not (root / path).is_file()]
            if missing_tests:
                errors.append(f"complete packet {packet.get('id')} has missing tests: {missing_tests}")
            evidence_dir = root / str(packet.get("evidence", ""))
            for name in ("verify.json", "SOL-REVIEW.md", "EXIT.md"):
                if not (evidence_dir / name).is_file():
                    errors.append(f"complete packet {packet.get('id')} missing closure evidence {name}")
            if packet.get("sol_verdict") != "APPROVE":
                errors.append(f"complete packet {packet.get('id')} requires Sol APPROVE")
            if isinstance(github_repo, str) and isinstance(packet.get("issue"), int):
                issue = github_issue(root, github_repo, packet["issue"])
                if issue is None or not str(issue.get("title", "")).startswith(f"[{packet.get('id')}]"):
                    errors.append(f"complete packet {packet.get('id')} GitHub issue does not exist or has wrong identity")
            commits = packet.get("commits", [])
            if not commits or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value) for value in commits):
                errors.append(f"complete packet {packet.get('id')} requires commit object ids")
            else:
                for commit in commits:
                    try:
                        if git_output(root, "cat-file", "-t", commit) != "commit":
                            errors.append(f"complete packet {packet.get('id')} references non-commit {commit}")
                    except subprocess.CalledProcessError:
                        errors.append(f"complete packet {packet.get('id')} references missing commit {commit}")
            plan_commit = data.get("plan_commit")
            if packet.get("id") == "P00" and (not commits or commits[0] != plan_commit):
                errors.append("complete packet P00 must close the frozen plan_commit")
            elif packet.get("id") != "P00" and commits and isinstance(plan_commit, str):
                try:
                    subprocess.run(
                        ["git", "merge-base", "--is-ancestor", plan_commit, commits[0]], cwd=root,
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                except subprocess.CalledProcessError:
                    errors.append(f"complete packet {packet.get('id')} commit is not based on plan_commit")
            verify_path = evidence_dir / "verify.json"
            verify: dict[str, Any] = {}
            if verify_path.is_file():
                try:
                    verify = json.loads(verify_path.read_text(encoding="utf-8"))
                    if verify.get("artifact_type") != "verify" or verify.get("status") != "complete":
                        errors.append(f"complete packet {packet.get('id')} has invalid verify state")
                    if verify.get("packet_id") != packet.get("id"):
                        errors.append(f"complete packet {packet.get('id')} verify packet_id mismatch")
                    checks = verify.get("checks")
                    if not isinstance(checks, list) or not checks or any(
                        not isinstance(check, dict) or check.get("exit") != 0 for check in checks
                    ):
                        errors.append(f"complete packet {packet.get('id')} verify checks are incomplete")
                    else:
                        commands = [str(check.get("command", "")) for check in checks]
                        if not any(command.strip() == "python3 -m pytest -q" for command in commands):
                            errors.append(f"complete packet {packet.get('id')} verify lacks full test suite")
                        for test_path in packet.get("tests", []):
                            if not any(test_path in command for command in commands):
                                errors.append(f"complete packet {packet.get('id')} verify lacks focused test {test_path}")
                        if not any("compileall" in command for command in commands):
                            errors.append(f"complete packet {packet.get('id')} verify lacks compilation check")
                    reviewed_tree = verify.get("reviewed_tree")
                    if not isinstance(reviewed_tree, str) or not re.fullmatch(r"[0-9a-f]{40}", reviewed_tree):
                        errors.append(f"complete packet {packet.get('id')} verify reviewed_tree is invalid")
                    elif commits:
                        try:
                            if git_output(root, "rev-parse", f"{commits[0]}^{{tree}}") != reviewed_tree:
                                errors.append(f"complete packet {packet.get('id')} commit tree differs from Sol-reviewed tree")
                        except subprocess.CalledProcessError:
                            pass
                    checksums = verify.get("artifact_checksums")
                    if not isinstance(checksums, dict) or not checksums:
                        errors.append(f"complete packet {packet.get('id')} verify lacks artifact checksums")
                    else:
                        for relative, expected in checksums.items():
                            artifact = evidence_dir / str(relative)
                            if (
                                not isinstance(relative, str) or Path(relative).is_absolute()
                                or ".." in Path(relative).parts or not artifact.is_file()
                                or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                                or sha256(artifact) != expected
                            ):
                                errors.append(f"complete packet {packet.get('id')} has invalid artifact checksum {relative}")
                    if commits:
                        try:
                            relative_verify = str(verify_path.relative_to(root))
                            base_verify = json.loads(git_output(root, "show", f"{commits[0]}:{relative_verify}"))
                            if strip_verify_finalizer_fields(base_verify) != strip_verify_finalizer_fields(verify):
                                errors.append(f"complete packet {packet.get('id')} rewrote reviewed verify commands")
                        except (ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
                            errors.append(f"complete packet {packet.get('id')} verify.json was not in reviewed tree")
                except json.JSONDecodeError:
                    errors.append(f"complete packet {packet.get('id')} verify.json is invalid JSON")
            review_path = evidence_dir / "SOL-REVIEW.md"
            if review_path.is_file():
                review_text = review_path.read_bytes().decode("utf-8")
                reviewed_tree = verify.get("reviewed_tree", "")
                base_review = None
                if commits:
                    try:
                        relative_review = str(review_path.relative_to(root))
                        base_review = git_bytes(root, "show", f"{commits[0]}:{relative_review}").decode("utf-8")
                    except (ValueError, subprocess.CalledProcessError):
                        pass
                if not isinstance(base_review, str) or not valid_approval_append(base_review, review_text, str(reviewed_tree)):
                    errors.append(f"complete packet {packet.get('id')} Sol review lacks final APPROVE")
                else:
                    session = approval_session(base_review, review_text, str(reviewed_tree))
                    if session is None or not codex_session_approves(session, str(reviewed_tree)):
                        errors.append(f"complete packet {packet.get('id')} lacks matching Codex Sol session evidence")
            exit_path = evidence_dir / "EXIT.md"
            if exit_path.is_file():
                exit_bytes = exit_path.read_bytes()
                exit_text = exit_bytes.decode("utf-8")
                if "Acceptance evidence" not in exit_text or "AT_BOUND" in exit_text:
                    errors.append(f"complete packet {packet.get('id')} EXIT.md does not prove acceptance")
                elif commits:
                    try:
                        relative_exit = str(exit_path.relative_to(root))
                        if not committed_file_matches(root, commits[0], relative_exit, exit_path):
                            errors.append(f"complete packet {packet.get('id')} EXIT.md differs from reviewed tree")
                    except (ValueError, subprocess.CalledProcessError):
                        errors.append(f"complete packet {packet.get('id')} EXIT.md was not in reviewed tree")

    graph = {
        packet["id"]: packet.get("depends_on", [])
        for packet in packets
        if isinstance(packet, dict) and isinstance(packet.get("id"), str)
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            errors.append(f"packet dependency cycle includes {node}")
            return
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for packet_id in graph:
        visit(packet_id)

    packet_by_id = {packet.get("id"): packet for packet in packets if isinstance(packet, dict)}
    for packet in packets:
        if not isinstance(packet, dict) or packet.get("state") != "complete":
            continue
        incomplete = [
            dependency for dependency in packet.get("depends_on", [])
            if packet_by_id.get(dependency, {}).get("state") != "complete"
        ]
        if incomplete:
            errors.append(f"complete packet {packet.get('id')} has incomplete dependencies: {incomplete}")

    allowed_status = {"planned", "in_progress", "blocked", "complete", "excluded", "deferred"}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            errors.append("requirement entries must be objects")
            continue
        rid = requirement.get("id")
        for field in (
            "id", "expected", "failure", "gate", "packet", "source", "disposition", "status",
        ):
            value = requirement.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"requirement {rid} missing non-empty {field}")
        if requirement.get("packet") not in packet_set:
            errors.append(f"requirement {rid} references unknown packet {requirement.get('packet')}")
        if requirement.get("status") not in allowed_status:
            errors.append(f"requirement {rid} has invalid status {requirement.get('status')}")
        expected_source = f"docs/execution/v1/REQUIREMENT-CATALOG.md#{rid}"
        if requirement.get("source") != expected_source:
            errors.append(f"requirement {rid} source must be {expected_source}")
        if requirement.get("disposition") not in {"ship", "evaluate-only", "defer", "exclude"}:
            errors.append(f"requirement {rid} has invalid disposition")
        owner = packet_by_id.get(requirement.get("packet"), {})
        if requirement.get("status") == "complete" and owner.get("state") != "complete":
            errors.append(f"complete requirement {rid} has incomplete owner packet")

    catalog_path = root / "docs/execution/v1/REQUIREMENT-CATALOG.md"
    if catalog_path.is_file():
        anchors = re.findall(r'<a id="([A-Z]+-[0-9]+)"', catalog_path.read_text(encoding="utf-8"))
        if len(anchors) != len(set(anchors)):
            errors.append("requirement catalog contains duplicate anchors")
        missing = sorted(set(requirement_ids) - set(anchors))
        extra = sorted(set(anchors) - set(requirement_ids))
        if missing:
            errors.append(f"requirements missing catalog anchors: {missing}")
        if extra:
            errors.append(f"catalog anchors missing registry rows: {extra}")

    for packet_id in packet_set:
        if not any(r.get("packet") == packet_id for r in requirements if isinstance(r, dict)):
            errors.append(f"packet {packet_id} owns no requirement")

    if ready:
        if data.get("status") != "sol_approved":
            errors.append("ready registry status must be sol_approved")
        plan_commit = data.get("plan_commit")
        approved_tree = data.get("approved_tree")
        if not isinstance(plan_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", plan_commit):
            errors.append("ready registry requires valid plan_commit")
        if not isinstance(approved_tree, str) or not re.fullmatch(r"[0-9a-f]{40}", approved_tree):
            errors.append("ready registry requires valid approved_tree")
        plan_digest = data.get("plan_sha256")
        if not isinstance(plan_digest, str) or len(plan_digest) != 64:
            errors.append("ready registry requires a 64-character plan_sha256")
        elif plan_path is not None and plan_path.is_file() and sha256(plan_path) != plan_digest:
            errors.append("plan_sha256 does not match plan_path")
        review = data.get("sol_plan_review")
        if not isinstance(review, dict) or review.get("verdict") != "APPROVE":
            errors.append("ready registry requires Sol APPROVE verdict")
        if isinstance(review, dict) and (review.get("blocking") or review.get("required")):
            errors.append("ready registry cannot retain unresolved Sol blocking/required findings")
        if not isinstance(review, dict) or not isinstance(review.get("session"), str):
            errors.append("ready registry requires the verified Sol session id")
        for packet in packets:
            if packet.get("issue") is None:
                errors.append(f"ready packet {packet.get('id')} requires a GitHub issue")
        if isinstance(plan_commit, str) and re.fullmatch(r"[0-9a-f]{40}", plan_commit):
            try:
                if git_output(root, "cat-file", "-t", plan_commit) != "commit":
                    errors.append("plan_commit is not a commit object")
                commit_tree = git_output(root, "rev-parse", f"{plan_commit}^{{tree}}")
                if commit_tree != approved_tree:
                    errors.append("plan_commit tree does not match approved_tree")
                if sha256(plan_path) != hashlib.sha256(
                    subprocess.run(
                        ["git", "show", f"{plan_commit}:{plan_rel}"], cwd=root, check=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    ).stdout
                ).hexdigest():
                    errors.append("current plan differs from approved plan_commit")
                expected_manifest = normative_manifest(root, plan_commit)
                if data.get("normative_manifest_sha256") != expected_manifest:
                    errors.append("normative_manifest_sha256 does not match plan_commit")
                # Compare the current working tree (including staged finalizer
                # edits) with the reviewed semantic commit. This lets --ready
                # reject an unauthorized file before the finalizer is committed.
                changed = set(filter(None, git_output(root, "diff", "--name-only", plan_commit).splitlines()))
                if changed - FINALIZER_PATHS:
                    errors.append(f"non-whitelisted finalizer paths changed: {sorted(changed - FINALIZER_PATHS)}")
                base_registry = json.loads(git_output(root, "show", f"{plan_commit}:docs/execution/v1/REQUIREMENTS.json"))
                if strip_finalizer_fields(base_registry) != strip_finalizer_fields(data):
                    errors.append("finalizer changed non-whitelisted registry fields")
                review_path = root / "docs/evidence/v1/L0-plan-review/SOL-REVIEW.md"
                if not committed_review_accepts_append(
                    root, plan_commit, "docs/evidence/v1/L0-plan-review/SOL-REVIEW.md",
                    review_path, str(approved_tree),
                ):
                    errors.append("Sol review finalization is not an exact append to the approved plan record")
                else:
                    base_review = git_bytes(
                        root, "show", f"{plan_commit}:docs/evidence/v1/L0-plan-review/SOL-REVIEW.md"
                    ).decode("utf-8")
                    current_review = review_path.read_bytes().decode("utf-8")
                    session = approval_session(base_review, current_review, str(approved_tree))
                    if session != review.get("session") or not codex_session_approves(str(session), str(approved_tree)):
                        errors.append("Sol approval envelope does not match the local Codex review session")
                base_verify = json.loads(git_output(root, "show", f"{plan_commit}:docs/evidence/v1/L0-plan-review/verify.json"))
                current_verify = json.loads(
                    (root / "docs/evidence/v1/L0-plan-review/verify.json").read_text(encoding="utf-8")
                )
                if strip_verify_finalizer_fields(base_verify) != strip_verify_finalizer_fields(current_verify):
                    errors.append("verify.json finalizer changed non-deterministic fields")
            except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                errors.append(f"plan_commit integrity check failed: {exc}")
        review_path = root / str(review.get("path", "")) if isinstance(review, dict) else None
        if review_path is None or not review_path.is_file():
            errors.append("Sol review artifact is missing")
        else:
            review_text = review_path.read_text(encoding="utf-8")
            if (
                not review_text.rstrip().endswith("Final verdict: **APPROVE**")
                or f"Approved staged tree: `{approved_tree}`" not in review_text
            ):
                errors.append("Sol review artifact lacks APPROVE and exact approved_tree")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", nargs="?", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--ready", action="store_true", help="require the frozen Sol-approved state")
    args = parser.parse_args()
    data = json.loads(args.registry.read_text(encoding="utf-8"))
    errors = validate(data, root=ROOT, ready=args.ready)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"ok: {len(data['requirements'])} requirements, {len(data['packets'])} packets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
