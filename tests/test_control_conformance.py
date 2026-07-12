"""P02 adversarial tests for frozen routing and compatibility comparison."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import control_conformance as conformance


@pytest.mark.parametrize(("routing_request", "rule", "detail"), [
    (conformance.RoutingRequest("what was said?", explicit_detail="efficient"), 1, "efficient"),
    (conformance.RoutingRequest("what was said?", timestamps="00:01,00:02"), 2, "transcript"),
    (conformance.RoutingRequest("What text is visible in the UI?"), 3, "balanced"),
    (conformance.RoutingRequest("Give a chronology of all topics"), 4, "balanced"),
    (conformance.RoutingRequest("What did the presenter explain?"), 5, "transcript"),
    (conformance.RoutingRequest(None), 6, "balanced"),
])
def test_routing_uses_frozen_priority(routing_request, rule, detail):
    decision = conformance.route_control(routing_request)
    assert decision["routing_version"] == "cheapest-control-v1"
    assert decision["matched_rule"] == rule
    assert decision["effective_frozen_control_flags"]["detail"] == detail


def test_explicit_supported_flags_are_mirrored_without_rerouting():
    decision = conformance.route_control(conformance.RoutingRequest(
        "What was said?", mirrored_flags={"resolution": 320, "no_whisper": True, "start": "00:04"},
        source_metadata={"kind": "local", "identity_sha256": "a" * 64},
    ))
    assert decision["matched_rule"] == 5
    assert decision["effective_frozen_control_flags"] == {
        "detail": "transcript", "resolution": 320, "no_whisper": True, "start": "00:04",
    }


@pytest.mark.parametrize("routing_request", [
    conformance.RoutingRequest("x", explicit_detail="evidence"),
    conformance.RoutingRequest("x", timestamps=""),
    conformance.RoutingRequest("x", mirrored_flags={"gold": "leak"}),
    conformance.RoutingRequest("x", mirrored_flags={"no_dedup": "maybe"}),
    conformance.RoutingRequest("x", source_metadata={"chapters": "outcome"}),
])
def test_routing_refuses_ambiguous_unknown_and_outcome_derived_input(routing_request):
    with pytest.raises(conformance.ConformanceRefusal):
        conformance.route_control(routing_request)


@pytest.mark.parametrize("flags", [
    {"max_frames": 0}, {"max_frames": True}, {"resolution": -1}, {"resolution": "512"},
    {"fps": 0}, {"fps": False}, {"timestamps": ""}, {"timestamps": "1,nope"},
    {"start": "nope"}, {"end": "-1"}, {"start": "00:03", "end": "00:02"},
    {"whisper": "other"}, {"whisper": "groq", "no_whisper": True}, {"no_whisper": 1},
    {"no_dedup": "false"},
])
def test_routing_rejects_invalid_complete_flag_matrix(flags):
    with pytest.raises(conformance.ConformanceRefusal):
        conformance.route_control(conformance.RoutingRequest("what was said", mirrored_flags=flags))


def test_mirrored_timestamps_activate_priority_two_and_precedence():
    from_flags = conformance.route_control(conformance.RoutingRequest(
        "What visible UI text changes?", mirrored_flags={"timestamps": "00:01,00:02"}))
    assert from_flags["matched_rule"] == 2
    assert from_flags["effective_frozen_control_flags"] == {"detail": "transcript", "timestamps": "00:01,00:02"}
    explicit_detail = conformance.route_control(conformance.RoutingRequest(
        "What visible UI text changes?", explicit_detail="balanced", timestamps="00:01"))
    assert explicit_detail["matched_rule"] == 1
    with pytest.raises(conformance.ConformanceRefusal, match="disagree"):
        conformance.route_control(conformance.RoutingRequest(
            "x", timestamps="00:01", mirrored_flags={"timestamps": "00:02"}))
    with pytest.raises(conformance.ConformanceRefusal):
        conformance.route_control(conformance.RoutingRequest("x", timestamps=1))  # type: ignore[arg-type]


def test_source_metadata_is_optional_but_complete_when_explicit():
    with pytest.raises(conformance.ConformanceRefusal):
        conformance.route_control(conformance.RoutingRequest("x", source_metadata={"kind": "local"}))


@pytest.mark.parametrize("stamp", ["1.5", "01:02.5", "01:02:03.5"])
def test_routing_accepts_runtime_fractional_timestamps(stamp: str):
    assert conformance.route_control(conformance.RoutingRequest("what was said", timestamps=stamp))["matched_rule"] == 2


@pytest.mark.parametrize("question", [
    "What graph changed while they spoke?", "What car movement is visible?", "What object motion happens?",
    "What logo looks like while they explain it?", "What person walks past?", "What animation does it show?",
])
def test_visual_phrasing_wins_before_speech_keywords(question: str):
    assert conformance.route_control(conformance.RoutingRequest(question))["matched_rule"] == 3


@pytest.mark.parametrize("metadata", [
    {"kind": "other", "identity_sha256": "a" * 64},
    {"kind": "local", "identity_sha256": "A" * 64},
    {"kind": "local", "identity_sha256": "short"},
])
def test_metadata_refuses_invalid_pre_outcome_values(metadata):
    with pytest.raises(conformance.ConformanceRefusal):
        conformance.route_control(conformance.RoutingRequest("x", source_metadata=metadata))


def test_routing_input_boundary_has_no_outcome_escape_hatch(tmp_path: Path):
    signature = inspect.signature(conformance.route_control)
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
    with pytest.raises(TypeError):
        conformance.RoutingRequest("x", gold_evidence=[])  # type: ignore[call-arg]
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"question": "x", "observed_score": 10}), encoding="utf-8")
    proc = subprocess.run([sys.executable, "tools/control_conformance.py", "route", "--request", str(request)],
                          text=True, capture_output=True)
    assert proc.returncode == 4
    assert "outcome-derived" in proc.stderr


def test_pair_order_delegates_to_p01_control_rule():
    assert conformance.paired_order("p02-case") == conformance.control_harness.paired_order("p02-case")


def test_normalization_permits_only_temporary_paths(tmp_path: Path):
    root = tmp_path / "run"
    root.mkdir()
    same = conformance.summarize_output(root, f"frame {root}/frames/frame_0000.jpg (t=00:01)\n", "", (root,))
    other = conformance.summarize_output(root, "frame /other/frames/frame_0000.jpg (t=00:01)\n", "", (root, Path("/other")))
    assert same["stdout"] == other["stdout"]
    assert conformance.compare_summaries(same, other) == []


def test_normalization_refuses_an_undeclared_absolute_path(tmp_path: Path):
    with pytest.raises(conformance.ConformanceRefusal, match="undeclared absolute"):
        conformance.normalize_text("leak /not-a-declared-root/file.txt", (tmp_path,))


def test_normalization_does_not_treat_public_url_as_local_path(tmp_path: Path):
    url = "https://www.youtube.com/watch?v=public-id"
    assert conformance.normalize_text(url, (tmp_path,)) == url


def test_undeclared_behavioral_difference_blocks():
    base = {"stdout": "same", "stderr": "", "frames": [], "transcript": [], "raw_manifest": []}
    changed = {**base, "transcript": [{"timestamp": "00:01", "text": "changed"}]}
    assert conformance.compare_summaries(base, changed) == ["transcript"]
    with pytest.raises(conformance.ConformanceRefusal, match="undeclared allowed difference"):
        conformance.compare_summaries(base, base, allowed=frozenset({"made-up"}))
    changed_manifest = {**base, "raw_manifest": [{"path": "x", "sha256": "0", "bytes": 1}]}
    assert conformance.compare_summaries(base, changed_manifest) == ["raw_manifest"]


def test_latency_allowance_requires_measurements_and_matches_declared_formula():
    with pytest.raises(conformance.ConformanceRefusal, match="missing deterministic"):
        conformance.latency_allowance_ms([1.0], 100.0)
    assert conformance.latency_allowance_ms([1.0, 2.0, 30.0], 100.0) == 28.0


def test_observed_process_and_provider_differences_block():
    control = {"process_calls": 4, "provider_network_calls": 0}
    assert conformance.compare_call_observations(control, {"process_calls": 4, "provider_network_calls": 0}) == []
    assert conformance.compare_call_observations(control, {"process_calls": 5, "provider_network_calls": 0}) == ["process_calls"]
    assert conformance.compare_call_observations(control, {"process_calls": 4, "provider_network_calls": 1}) == ["provider_network_calls"]


def test_candidate_identity_requires_the_declared_repository_root(tmp_path: Path):
    with pytest.raises(conformance.ConformanceRefusal, match="declared repository root"):
        conformance.candidate_identity(Path.cwd(), tmp_path)


@pytest.mark.parametrize("status", [" M skills/watch/scripts/watch.py", "M  skills/watch/scripts/watch.py", "?? skills/watch/scripts/shadow.py"])
def test_candidate_identity_refuses_dirty_staged_and_untracked_runtime(tmp_path: Path, monkeypatch, status: str):
    root = tmp_path / "repo"
    for relative in ("skills/watch/scripts/watch.py", "skills/watch/scripts/config.py", "skills/watch/scripts/download.py",
                     "skills/watch/scripts/frames.py", "skills/watch/scripts/transcribe.py", "skills/watch/scripts/whisper.py"):
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("# fixture\n", encoding="utf-8")
    def fake_git(_repo, *args):
        if args[:2] == ("rev-parse", "--show-toplevel"): return str(root)
        if args[:3] == ("status", "--porcelain=v1", "--untracked-files=all"): return status
        return "fixture"
    monkeypatch.setattr(conformance, "_git", fake_git)
    with pytest.raises(conformance.ConformanceRefusal, match="runtime subtree must be clean"):
        conformance.candidate_identity(root, root)


def test_raw_receipt_hashes_are_per_arm_and_not_loop_state(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "stdout.raw").write_bytes(b"control")
    (first / "stderr.raw").write_bytes(b"one")
    (second / "stdout.raw").write_bytes(b"candidate")
    (second / "stderr.raw").write_bytes(b"two")
    assert conformance.raw_receipt_hashes(first) != conformance.raw_receipt_hashes(second)


@pytest.mark.parametrize("snippet", [
    "import socket; socket.socket().connect(('127.0.0.1', 1))",
    "import socket; socket.socket().sendto(b'x', ('127.0.0.1', 1))",
    "import urllib.request; urllib.request.urlopen('http://example.invalid')",
    "import subprocess; subprocess.run(['/usr/bin/curl', '--version'])",
])
def test_python_audit_blocks_socket_urlopen_and_arbitrary_executable(tmp_path: Path, snippet: str):
    audit = tmp_path / "audit"; audit.mkdir()
    (audit / "sitecustomize.py").write_text(conformance._audit_source(), encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    env = {**dict(__import__("os").environ), "PYTHONPATH": str(audit), "P02_AUDIT_LOG": str(log),
           "P02_ALLOWED_EXECUTABLES": "[]"}
    proc = subprocess.run([sys.executable, "-c", snippet], text=True, capture_output=True, env=env)
    assert proc.returncode != 0
    assert log.read_text(encoding="utf-8")


def test_actual_local_evidence_fails_open_once_without_provider_call(cut_clip: Path, tmp_path: Path):
    result = conformance.run_evidence_fallback(
        cut_clip, candidate_root=Path.cwd(), out_dir=tmp_path / "fallback",
        question="What happens after the transition?", resolution=160, max_frames=4,
    )
    assert result["evidence_exit"] == result["balanced_exit"] == 0
    assert result["warning_count"] == 1
    assert result["fallback_order"] == ["evidence", "balanced"]
    assert result["evidence_calls"]["provider_network_calls"] == 0
    assert result["balanced_calls"]["provider_network_calls"] == 0
    assert result["evidence_calls"]["process_calls"] >= 1
    assert result["evidence"]["frames"] == result["balanced"]["frames"]
    assert result["evidence"]["transcript"] == result["balanced"]["transcript"]


@pytest.mark.parametrize("kind", ["success", "failure", "timeout", "fallback"])
def test_deterministic_fixture_pairs_cover_all_outcomes(kind: str, tmp_path: Path):
    result = conformance.run_deterministic_fixture_pair(kind, tmp_path / kind)
    assert result["differences"] == []
    assert result["arms"]["control"]["exit_class"] == result["arms"]["candidate"]["exit_class"]
    if kind == "failure":
        assert result["arms"]["control"]["failure_class"] == "invalid_source"
    if kind == "timeout":
        assert result["arms"]["control"]["failure_class"] == "timeout"
    if kind == "fallback":
        assert result["arms"]["control"]["fallback_order"] == ["native", "sidecar"]


def test_deterministic_fixture_rejects_failure_and_fallback_order_mismatch(tmp_path: Path):
    with pytest.raises(conformance.ConformanceRefusal, match="fixture behavioral difference"):
        conformance.run_deterministic_fixture_pair("failure", tmp_path / "failure", candidate_kind="success")
    with pytest.raises(conformance.ConformanceRefusal, match="fixture behavioral difference"):
        conformance.run_deterministic_fixture_pair("fallback", tmp_path / "fallback", candidate_kind="success")
