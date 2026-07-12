"""Synthetic, offline checks for the custodian-only development runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import corpus_registry
from tools import run_development_conformance as runner


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry(source_hash: str) -> dict:
    registry = {
        "schema_version": 1, "registry_version": "corpus-registry-v1", "status": "sealed",
        "custodian_id": "custodian", "development_executor_ids": ["dev-executor"],
        "frozen": {"candidate_commit": "a" * 40, "candidate_config_hash": "b" * 64,
                   "routing_epoch": "routing", "prompt_epoch": "prompt", "reader_epoch": "reader",
                   "grader_epoch": "grader", "evaluator_version": "v1", "exclusions": [],
                   "supported_classes": ["targeted"], "supported_environments": ["macos-arm64-python-3.14"],
                   "minimum_confirmatory_families": 5, "minimum_confirmatory_families_by_class": {"targeted": 3}},
        "families": [
            {"family_id": "dev-family", "split": "development", "question_classes": ["targeted"],
             "identities": [{"identity_id": "dev-source", "identity_sha256": source_hash}]},
            *[{"family_id": f"reserve-family-{index}", "split": "confirmatory", "question_classes": ["targeted"],
               "identities": [{"identity_id": f"reserve-source-{index}", "identity_sha256": f"{index:064x}"}]}
              for index in range(1, 6)],
        ],
    }
    registry["seal_sha256"] = corpus_registry.registry_fingerprint(registry)
    return registry


def _manifest(tmp_path: Path, registry: dict, source: Path, config: Path) -> dict:
    return {"schema_version": 1, "actor_id": "dev-executor", "registry_seal_sha256": registry["seal_sha256"],
            "candidate_commit": "a" * 40, "candidate_config_path": str(config), "candidate_config_sha256": _sha(config),
            "environment": {"environment_id": "macos-arm64-python-3.14", "tools": {"python": "/fake/python", "ffmpeg": "/fake/ffmpeg", "ffprobe": "/fake/ffprobe", "yt_dlp": "/fake/yt-dlp"}, "locale": "C", "network_policy": "offline", "timeout_seconds": 3, "retry_policy": {"harness_attempts": 1}},
            "cases": [{"identity_id": "dev-source", "source": str(source), "question": "What synthetic event happens?", "question_class": "targeted", "frozen_flags": {"detail": "balanced", "max_frames": None, "resolution": 320, "fps": None, "timestamps": None, "start": None, "end": None, "no_whisper": True, "whisper": None, "no_dedup": False}, "obligations": ["synthetic event"], "gold_evidence": None, "gold_unavailable_reason": "awaiting independent annotation", "reader": {"model_epoch": "reader", "prompt_sha256": "c" * 64}}]}


def test_runner_emits_locator_free_case_and_run_observations(tmp_path: Path, monkeypatch):
    repo, control, output = tmp_path / "repo", tmp_path / "control", tmp_path / "output"
    repo.mkdir(); control.mkdir()
    source, config = tmp_path / "synthetic.mp4", tmp_path / "config.json"
    source.write_bytes(b"generated-local-media")
    config.write_bytes(b"candidate-config")
    registry = _registry(_sha(source)); registry["frozen"]["candidate_config_hash"] = _sha(config)
    registry["seal_sha256"] = corpus_registry.registry_fingerprint(registry)
    manifest = _manifest(tmp_path, registry, source, config)
    registry_path, manifest_path = tmp_path / "registry.json", tmp_path / "manifest.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(runner.control_harness, "assert_clean_detached_control", lambda *args: None)
    monkeypatch.setattr(runner.control_conformance, "candidate_identity", lambda *args: {"candidate_commit": "a" * 40, "candidate_index_sha256": "d" * 64, "candidate_runtime_sha256": "e" * 64})
    monkeypatch.setattr(runner.control_harness, "capture_tool_versions", lambda tools: {name: "fake 1" for name in tools})
    monkeypatch.setattr(runner.control_harness, "capture_tool_sha256", lambda tools: {name: "f" * 64 for name in tools})

    def fake_pair(case, **kwargs):
        assert case["source"] == str(source)
        return {"paired_order": ["control", "candidate"], "control_commit": runner.control_harness.CONTROL_COMMIT,
                "candidate": {"candidate_commit": "a" * 40}, "arms": {arm: {"exit_class": "success"} for arm in ("control", "candidate")}}

    result = runner.run(manifest_path, registry_path, repo=repo, control_worktree=control, output_root=output, run_pair=fake_pair)
    assert result["runs"] == 2
    emitted = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file())
    assert str(source) not in emitted
    assert "reserve-source" not in emitted
    assert json.loads((output / "cases.jsonl").read_text().splitlines()[0])["split"] == "development"


@pytest.mark.parametrize("mutate, message", [
    (lambda manifest, registry: manifest["cases"][0].update(identity_id="reserve-source-1"), "authorized development identity"),
    (lambda manifest, registry: manifest["cases"][0].update(question=""), "fixed non-empty question"),
    (lambda manifest, registry: manifest["cases"][0].update(obligations=[]), "gold obligations"),
    (lambda manifest, registry: manifest["cases"][0].update(source="/missing-media.mp4"), "existing absolute file"),
])
def test_runner_refuses_bad_local_mappings(tmp_path: Path, mutate, message):
    source, config = tmp_path / "synthetic.mp4", tmp_path / "config.json"
    source.write_bytes(b"generated-local-media"); config.write_bytes(b"candidate-config")
    registry = _registry(_sha(source)); registry["frozen"]["candidate_config_hash"] = _sha(config)
    registry["seal_sha256"] = corpus_registry.registry_fingerprint(registry)
    manifest = _manifest(tmp_path, registry, source, config); mutate(manifest, registry)
    with pytest.raises(runner.DevelopmentRunnerRefusal, match=message):
        runner._validate_manifest(manifest, registry, repo=tmp_path)


def test_runner_refuses_nonempty_output_before_reading_manifest(tmp_path: Path):
    output = tmp_path / "output"; output.mkdir(); (output / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(runner.DevelopmentRunnerRefusal, match="output root must be empty"):
        runner.run(tmp_path / "missing.json", tmp_path / "registry.json", repo=tmp_path / "repo", control_worktree=tmp_path / "control", output_root=output)


def test_runner_accepts_a_hashed_public_url_only_with_network_enabled(tmp_path: Path):
    source, config = tmp_path / "synthetic.mp4", tmp_path / "config.json"
    source.write_bytes(b"generated-local-media"); config.write_bytes(b"candidate-config")
    url = "https://example.invalid/public-development-media.mp4"
    registry = _registry(hashlib.sha256(url.encode("utf-8")).hexdigest())
    registry["frozen"]["candidate_config_hash"] = _sha(config)
    registry["seal_sha256"] = corpus_registry.registry_fingerprint(registry)
    manifest = _manifest(tmp_path, registry, source, config)
    manifest["environment"]["network_policy"] = "enabled"
    manifest["cases"][0]["source"] = url
    runner._validate_manifest(manifest, registry, repo=tmp_path)
    assert runner._source_kind_and_hash(url)[0] == "url"
