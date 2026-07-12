import copy
import hashlib
import json
import subprocess
from pathlib import Path

from tools.validate_v1_execution import (
    ROOT, codex_session_approves, committed_file_matches, committed_review_accepts_append,
    strip_finalizer_fields, strip_verify_finalizer_fields, valid_approval_append, validate,
)


REGISTRY = ROOT / "docs/execution/v1/REQUIREMENTS.json"


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_current_execution_registry_is_structurally_valid():
    assert validate(load_registry()) == []


def test_unknown_packet_reference_is_rejected():
    data = load_registry()
    data["requirements"][0]["packet"] = "P404"
    assert any("unknown packet" in error for error in validate(data))


def test_duplicate_requirement_is_rejected():
    data = load_registry()
    data["requirements"].append(copy.deepcopy(data["requirements"][0]))
    assert any("duplicate requirement ids" in error for error in validate(data))


def test_ready_state_requires_matching_plan_hash():
    data = load_registry()
    data["status"] = "sol_approved"
    data["plan_commit"] = "a" * 40
    data["approved_tree"] = "b" * 40
    data["plan_sha256"] = "0" * 64
    data["sol_plan_review"] = {
        "model": "gpt-5.6-sol",
        "verdict": "APPROVE",
        "path": "review.md",
        "blocking": [],
        "required": [],
    }
    assert "plan_sha256 does not match plan_path" in validate(data, ready=True)


def test_ready_state_rejects_fabricated_commit_and_tree_ids():
    data = load_registry()
    data["status"] = "sol_approved"
    data["plan_commit"] = "a" * 40
    data["approved_tree"] = "b" * 40
    data["plan_sha256"] = hashlib.sha256(
        (ROOT / data["plan_path"]).read_bytes()
    ).hexdigest()
    data["normative_manifest_sha256"] = "c" * 64
    data["sol_plan_review"] = {
        "model": "gpt-5.6-sol", "verdict": "APPROVE",
        "path": "docs/evidence/v1/L0-plan-review/SOL-REVIEW.md",
        "blocking": [], "required": [],
    }
    for packet in data["packets"]:
        packet["issue"] = 1
    assert any("integrity check failed" in error for error in validate(data, ready=True))


def test_catalog_anchor_removal_is_rejected(tmp_path):
    data = load_registry()
    copied = tmp_path / "docs/execution/v1"
    copied.mkdir(parents=True)
    for name in (
        "CONTROL.md", "MEASUREMENT.md", "CONTRACTS.md", "SUPPORT.md", "PROVENANCE.md",
        "EVIDENCE-SCHEMAS.md", "PROTOCOL.md", "CHAIN.md", "evidence-schema-v1.json",
    ):
        (copied / name).write_text("placeholder", encoding="utf-8")
    catalog = (ROOT / "docs/execution/v1/REQUIREMENT-CATALOG.md").read_text(encoding="utf-8")
    (copied / "REQUIREMENT-CATALOG.md").write_text(
        catalog.replace('<a id="GOV-001"></a>', ""), encoding="utf-8"
    )
    plan = tmp_path / data["plan_path"]
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("plan", encoding="utf-8")
    assert any("GOV-001" in error for error in validate(data, root=tmp_path))


def test_finalizer_normalization_preserves_semantic_changes():
    before = load_registry()
    after = copy.deepcopy(before)
    after["status"] = "sol_approved"
    after["plan_commit"] = "a" * 40
    after["requirements"][0]["expected"] = "silently changed"
    assert strip_finalizer_fields(before) != strip_finalizer_fields(after)


def test_missing_packet_traceability_field_is_rejected():
    data = load_registry()
    del data["packets"][0]["evidence"]
    assert any("missing evidence" in error for error in validate(data))


def test_fake_complete_packet_is_rejected():
    data = load_registry()
    packet = data["packets"][1]
    packet.update(state="complete", issue="not-an-issue", tests=["tests/does_not_exist.py"])
    data["requirements"][3]["status"] = "complete"
    errors = validate(data)
    assert any("positive GitHub issue" in error for error in errors)
    assert any("missing tests" in error for error in errors)
    assert any("requires Sol APPROVE" in error for error in errors)
    assert any("requires commit object ids" in error for error in errors)
    assert any("incomplete dependencies" in error for error in errors)


def test_finalizer_cannot_replace_sol_model_or_path():
    before = load_registry()
    after = copy.deepcopy(before)
    after["sol_plan_review"]["model"] = "fabricated"
    after["sol_plan_review"]["path"] = "fabricated.md"
    assert strip_finalizer_fields(before) != strip_finalizer_fields(after)


def test_confirmatory_run_is_reachable_only_through_authorized_opening():
    data = load_registry()
    graph = {packet["id"]: packet["depends_on"] for packet in data["packets"]}

    def ancestors(node):
        result, pending = set(), list(graph[node])
        while pending:
            current = pending.pop()
            if current not in result:
                result.add(current)
                pending.extend(graph[current])
        return result

    assert "P30" in ancestors("P29")
    assert "P29" in ancestors("P31")


def test_sol_approval_must_append_to_unchanged_review_history():
    tree = "a" * 40
    base = "# Prior review\n\nVerdict: **CHANGES_REQUIRED**\n"
    envelope = (
        "\n## Final approval\n\nModel: `gpt-5.6-sol`\n\n"
        "Session: `019f5430-aa10-7532-adaa-18cc39805acc`\n\n"
        f"Approved staged tree: `{tree}`\n\nFinal verdict: **APPROVE**\n"
    )
    assert valid_approval_append(base, base + envelope, tree)
    assert not valid_approval_append(base, "# Replaced\n" + envelope, tree)
    assert not valid_approval_append(base, (base + envelope).replace(
        "019f5430-aa10-7532-adaa-18cc39805acc", "------------------------------------"
    ), tree)


def test_verify_finalizer_cannot_rewrite_recorded_commands():
    before = {"status": "provisional", "checks": [{"command": "pytest", "exit": 0}], "reviewed_tree": "0" * 40}
    after = copy.deepcopy(before)
    after.update(status="complete", reviewed_tree="a" * 40)
    assert strip_verify_finalizer_fields(before) == strip_verify_finalizer_fields(after)
    after["checks"][0]["command"] = "never executed"
    assert strip_verify_finalizer_fields(before) != strip_verify_finalizer_fields(after)


def test_session_approval_checks_the_complete_final_message(monkeypatch):
    tree = "a" * 40
    event = {
        "type": "response_item",
        "payload": {"role": "assistant", "content": [
            {"type": "output_text", "text": "DENY first. "},
            {"type": "output_text", "text": f"APPROVE {tree}"},
        ]},
    }

    class Candidate:
        def read_text(self, encoding=None):
            return json.dumps(event)

    class Sessions:
        def glob(self, pattern):
            return [Candidate()]

    class Home:
        def __truediv__(self, other):
            return Sessions()

    monkeypatch.setattr(Path, "home", staticmethod(lambda: Home()))
    assert not codex_session_approves("019f5430-aa10-7532-adaa-18cc39805acc", tree)


def test_exact_review_append_rejects_line_ending_rewrite():
    tree = "a" * 40
    base = "# Review\r\n\r\nOriginal finding.\r\n"
    envelope = (
        "\n## Final approval\n\nModel: `gpt-5.6-sol`\n\n"
        "Session: `019f5430-aa10-7532-adaa-18cc39805acc`\n\n"
        f"Approved staged tree: `{tree}`\n\n"
        "Final verdict: **APPROVE**\n"
    )
    assert valid_approval_append(base, base + envelope, tree)
    assert not valid_approval_append(base, base.replace("\r\n", "\n") + envelope, tree)


def _commit_crlf_fixture(tmp_path, relative, content):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    subprocess.run(["git", "add", relative], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    return path, subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def test_validator_io_rejects_crlf_rewrite_of_committed_exit(tmp_path):
    relative = "docs/evidence/v1/P00/EXIT.md"
    original = b"# Exit\r\n\r\nAcceptance evidence\r\n"
    path, commit = _commit_crlf_fixture(tmp_path, relative, original)
    assert committed_file_matches(tmp_path, commit, relative, path)
    path.write_bytes(original.replace(b"\r\n", b"\n"))
    assert not committed_file_matches(tmp_path, commit, relative, path)


def test_validator_io_rejects_crlf_rewrite_of_committed_review(tmp_path):
    relative = "docs/evidence/v1/P00/SOL-REVIEW.md"
    base = b"# Review\r\n\r\nVerdict: **CHANGES_REQUIRED**\r\n"
    path, commit = _commit_crlf_fixture(tmp_path, relative, base)
    tree = "a" * 40
    envelope = (
        "\n## Final approval\n\nModel: `gpt-5.6-sol`\n\n"
        "Session: `019f5430-aa10-7532-adaa-18cc39805acc`\n\n"
        f"Approved staged tree: `{tree}`\n\nFinal verdict: **APPROVE**\n"
    ).encode()
    path.write_bytes(base + envelope)
    assert committed_review_accepts_append(tmp_path, commit, relative, path, tree)
    path.write_bytes(base.replace(b"\r\n", b"\n") + envelope)
    assert not committed_review_accepts_append(tmp_path, commit, relative, path, tree)
