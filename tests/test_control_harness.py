import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import control_harness


def _commit_control_fixture(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    script = repo / "skills/watch/scripts/watch.py"
    script.parent.mkdir(parents=True)
    (script.parent / "fixture_helper.py").write_text("VALUE = 'fixture'\n", encoding="utf-8")
    script.write_text(
        "from pathlib import Path\n"
        "import argparse\n"
        "import os\n"
        "import fixture_helper\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('source')\n"
        "p.add_argument('--detail')\n"
        "p.add_argument('--resolution')\n"
        "p.add_argument('--out-dir')\n"
        "p.add_argument('--max-frames')\n"
        "p.add_argument('--fps')\n"
        "p.add_argument('--timestamps')\n"
        "p.add_argument('--start')\n"
        "p.add_argument('--end')\n"
        "p.add_argument('--whisper')\n"
        "p.add_argument('--no-whisper', action='store_true')\n"
        "p.add_argument('--no-dedup', action='store_true')\n"
        "a = p.parse_args()\n"
        "source_bytes = Path(a.source).read_bytes() if not a.source.startswith(('http://', 'https://')) else b''\n"
        "if source_bytes == b'mutate-control':\n"
        "    Path(__file__).write_text('# Control was changed\\n')\n"
        "if source_bytes == b'spawn-resistant-child':\n"
        "    subprocess.Popen([sys.executable, '-c', 'import signal,time,sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(2); open(sys.argv[1], \"w\").write(\"survived\")', str(Path(a.source).with_suffix('.child-survived'))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)\n"
        "    time.sleep(60)\n"
        "Path(a.out_dir).mkdir(parents=True, exist_ok=True)\n"
        "if a.source.startswith(('http://', 'https://')):\n"
        "    template = str(Path(a.out_dir, 'download', 'video.%(ext)s'))\n"
        "    subprocess.run(['yt-dlp', '-o', template, '--', a.source], check=False)\n"
        "    if a.source.endswith('caption-drift'):\n"
        "        subprocess.run(['yt-dlp', '-o', template, '--', a.source], check=False)\n"
        "Path(a.out_dir, 'raw-output.txt').write_text('unchanged raw output\\n')\n"
        "Path(a.out_dir, 'environment.txt').write_text('|'.join(str(os.environ.get(name)) for name in ('PYTHONPATH', 'PYTHONHOME', 'ARBITRARY_SECRET', 'OPENAI_API_KEY')))\n"
        "print('control stdout')\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text("ignored-injection.py\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "frozen fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    return repo, commit


def _fake_tool(tmp_path: Path, name: str, version: str) -> Path:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | os.stat(path).st_mode | 0o111)
    return path


def _fake_ytdlp(tmp_path: Path) -> Path:
    path = tmp_path / "yt-dlp"
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then printf '%s\\n' 'yt-dlp fixture 1'; exit 0; fi\n"
        "template=; want=0; source=\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$want\" = 1 ]; then template=$arg; want=0; continue; fi\n"
        "  case \"$arg\" in -o|--output) want=1 ;; http://*|https://*) source=$arg ;; esac\n"
        "done\n"
        "dir=$(dirname \"$template\"); mkdir -p \"$dir\"\n"
        "case \"$source\" in\n"
        "  *caption-good) printf 'WEBVTT\\n\\n00:00:00.000 --> 00:00:01.000\\ngood caption\\n' > \"$dir/video.en.vtt\" ;;\n"
        "  *caption-drift)\n"
        "    if [ -f \"$dir/.called\" ]; then text='drifted caption'; else text='good caption'; touch \"$dir/.called\"; fi\n"
        "    printf 'WEBVTT\\n\\n00:00:00.000 --> 00:00:01.000\\n%s\\n' \"$text\" > \"$dir/video.en.vtt\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _case(tmp_path: Path) -> dict:
    fake_ffmpeg = _fake_tool(tmp_path, "ffmpeg", "ffmpeg fixture 1")
    fake_ffprobe = _fake_tool(tmp_path, "ffprobe", "ffprobe fixture 1")
    fake_ytdlp = _fake_ytdlp(tmp_path)
    python = Path(sys.executable).resolve()
    versions = control_harness.capture_tool_versions({
        "python": str(python), "ffmpeg": str(fake_ffmpeg), "ffprobe": str(fake_ffprobe), "yt_dlp": str(fake_ytdlp),
    })
    tool_paths = {"python": str(python), "ffmpeg": str(fake_ffmpeg), "ffprobe": str(fake_ffprobe), "yt_dlp": str(fake_ytdlp)}
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"fixture media bytes")
    return {
        "schema_version": 1,
        "case_id": "control-fixture-001",
        "source": str(source),
        "source_identity": {
            "kind": "local", "identity_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "caption_sha256": None,
        },
        "question": "What happens?",
        "frozen_flags": {
            "detail": "balanced", "max_frames": None, "resolution": 512, "fps": None,
            "timestamps": None, "start": None, "end": None, "no_whisper": True,
            "whisper": None, "no_dedup": False,
        },
        "environment": {
            "tools": tool_paths,
            "tool_versions": versions,
            "tool_sha256": control_harness.capture_tool_sha256(tool_paths),
            "os": platform.system(), "architecture": platform.machine(), "locale": "C",
            "network_policy": "offline", "cookie_input_policy": "none", "timeout_seconds": 10,
            "invocation_policy": {"harness_attempts": 1},
        },
        "reader": {"model_epoch": "reader-fixture-v1", "prompt_sha256": "a" * 64},
    }


def test_prepare_creates_clean_detached_worktree(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    assert control == (tmp_path / "control").resolve()
    control_harness.assert_clean_detached_control(control, commit)
    assert not list((control / "skills/watch/scripts").glob("__pycache__"))
    assert subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=control).returncode != 0


def test_dirty_control_is_refused_before_execution(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    (control / "dirty.txt").write_text("no", encoding="utf-8")
    with pytest.raises(control_harness.ControlIntegrityError, match="dirty"):
        control_harness.run_control(_case(tmp_path), control, tmp_path / "out", tmp_path / "receipt", commit)
    assert not (tmp_path / "out").exists()


def test_ignored_injection_in_control_worktree_is_refused(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    (control / "ignored-injection.py").write_text("raise SystemExit('injected')\n", encoding="utf-8")
    with pytest.raises(control_harness.ControlIntegrityError, match="dirty"):
        control_harness.assert_clean_detached_control(control, commit)


def test_run_preserves_raw_output_and_records_deterministic_pair_order(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    case = _case(tmp_path)
    receipt = control_harness.run_control(case, control, tmp_path / "out", tmp_path / "receipt", commit)
    assert receipt["control_commit"] == commit
    assert receipt["paired_order"] == list(control_harness.paired_order(case["case_id"]))
    assert receipt["control_order"] in {1, 2}
    assert receipt["control_clean_after"] is True
    assert (tmp_path / "receipt/run.json").is_file()
    assert (tmp_path / "receipt/stdout.raw").read_text(encoding="utf-8") == "control stdout\n"
    output = tmp_path / "out/raw-output.txt"
    assert output.read_text(encoding="utf-8") == "unchanged raw output\n"
    assert (tmp_path / "out/environment.txt").read_text(encoding="utf-8") == "None|None|None|None"
    environment_output = tmp_path / "out/environment.txt"
    assert receipt["raw_output_manifest"] == [
        {
            "path": "environment.txt", "bytes": environment_output.stat().st_size,
            "sha256": hashlib.sha256(environment_output.read_bytes()).hexdigest(),
        },
        {
            "path": "raw-output.txt", "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        },
    ]
    control_harness.assert_clean_detached_control(control, commit)


def test_minimal_environment_drops_python_overrides_and_arbitrary_secrets(tmp_path, monkeypatch):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    monkeypatch.setenv("PYTHONPATH", "/attacker/pythonpath")
    monkeypatch.setenv("PYTHONHOME", "/attacker/pythonhome")
    monkeypatch.setenv("ARBITRARY_SECRET", "do-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-leak")
    control_harness.run_control(_case(tmp_path), control, tmp_path / "out", tmp_path / "receipt", commit)
    assert (tmp_path / "out/environment.txt").read_text(encoding="utf-8") == "None|None|None|None"


def test_control_changed_during_run_is_refused_but_receipt_is_preserved(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    case = _case(tmp_path)
    source = Path(case["source"])
    source.write_bytes(b"mutate-control")
    case["source_identity"]["identity_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt_dir = tmp_path / "receipt"
    with pytest.raises(control_harness.ControlIntegrityError, match="integrity refusal after run"):
        control_harness.run_control(case, control, tmp_path / "out", receipt_dir, commit)
    receipt = (receipt_dir / "run.json").read_text(encoding="utf-8")
    assert '"control_clean_after": false' in receipt
    assert '"integrity_failure": "Control worktree is dirty"' in receipt


def test_unpinned_tool_version_and_nonempty_output_are_refused(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    case = _case(tmp_path)
    case["environment"]["tool_versions"]["ffmpeg"] = "not the observed version"
    with pytest.raises(control_harness.ControlIntegrityError, match="version drifted"):
        control_harness.run_control(case, control, tmp_path / "out", tmp_path / "receipt", commit)
    case = _case(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "prior.txt").write_text("prior", encoding="utf-8")
    with pytest.raises(control_harness.ControlIntegrityError, match="must be empty"):
        control_harness.run_control(case, control, out, tmp_path / "receipt", commit)


def test_same_resolved_output_and_receipt_directory_is_refused(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    shared = tmp_path / "shared"
    with pytest.raises(control_harness.ControlIntegrityError, match="must not overlap"):
        control_harness.run_control(_case(tmp_path), control, shared, shared / ".." / "shared", commit)


@pytest.mark.parametrize("out_name,receipt_name", [("out", "out/receipt"), ("receipt/out", "receipt")])
def test_ancestor_descendant_output_and_receipt_directories_are_refused(tmp_path, out_name, receipt_name):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    with pytest.raises(control_harness.ControlIntegrityError, match="must not overlap"):
        control_harness.run_control(
            _case(tmp_path), control, tmp_path / out_name, tmp_path / receipt_name, commit,
        )


def test_executable_content_change_with_same_version_is_refused(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    case = _case(tmp_path)
    ffmpeg = Path(case["environment"]["tools"]["ffmpeg"])
    probe_marker = tmp_path / "version-probe-ran"
    ffmpeg.write_text(
        ffmpeg.read_text(encoding="utf-8") + f"touch '{probe_marker}'\n",
        encoding="utf-8",
    )
    with pytest.raises(control_harness.ControlIntegrityError, match="content drifted"):
        control_harness.run_control(case, control, tmp_path / "out", tmp_path / "receipt", commit)
    assert not probe_marker.exists()


def test_version_probes_use_minimal_scrubbed_environment(tmp_path, monkeypatch):
    ffmpeg = _fake_tool(
        tmp_path, "ffmpeg",
        "ffmpeg fixture 1",
    )
    probe_marker = tmp_path / "probe-secret-leaked"
    ffmpeg.write_text(
        "#!/bin/sh\n"
        f"if [ -n \"$ARBITRARY_SECRET\" ]; then touch '{probe_marker}'; fi\n"
        "printf '%s\\n' 'ffmpeg fixture 1'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBITRARY_SECRET", "must-not-reach-probe")
    python = Path(sys.executable).resolve()
    paths = {
        "python": str(python), "ffmpeg": str(ffmpeg),
        "ffprobe": str(_fake_tool(tmp_path, "ffprobe", "ffprobe fixture 1")),
        "yt_dlp": str(_fake_tool(tmp_path, "yt-dlp", "yt-dlp fixture 1")),
    }
    assert control_harness.capture_tool_versions(paths)["ffmpeg"] == "ffmpeg fixture 1"
    assert not probe_marker.exists()


def test_case_requires_all_provenance_and_policy_fields(tmp_path):
    case = _case(tmp_path)
    del case["reader"]["model_epoch"]
    with pytest.raises(control_harness.ControlIntegrityError, match="model_epoch"):
        control_harness.validate_case(case)
    case = _case(tmp_path)
    case["environment"]["invocation_policy"]["harness_attempts"] = 2
    with pytest.raises(control_harness.ControlIntegrityError, match="one upstream invocation"):
        control_harness.validate_case(case)
    case = _case(tmp_path)
    case["source_identity"]["sidecar_path"] = "/tmp/not-consumed.vtt"
    with pytest.raises(control_harness.ControlIntegrityError, match="exactly"):
        control_harness.validate_case(case)
    case = _case(tmp_path)
    case["environment"]["invocation_policy"]["retry_policy"] = "none"
    with pytest.raises(control_harness.ControlIntegrityError, match="only harness_attempts"):
        control_harness.validate_case(case)


def test_source_kind_and_caption_provenance_are_pinned_and_verified(tmp_path):
    case = _case(tmp_path)
    case["source_identity"]["kind"] = "url"
    with pytest.raises(control_harness.ControlIntegrityError, match="HTTP"):
        control_harness.validate_case(case)
    case = _case(tmp_path)
    case["source"] = "https://example.invalid/video"
    case["source_identity"]["kind"] = "local"
    case["source_identity"]["identity_sha256"] = hashlib.sha256(case["source"].encode()).hexdigest()
    with pytest.raises(control_harness.ControlIntegrityError, match="local source_identity"):
        control_harness.validate_case(case)
    case = _case(tmp_path)
    case["source_identity"]["caption_sha256"] = hashlib.sha256(b"unrelated-sidecar").hexdigest()
    with pytest.raises(control_harness.ControlIntegrityError, match="does not consume a sidecar"):
        control_harness.validate_case(case)


def _url_case(tmp_path: Path, suffix: str, expected_caption: bytes | None) -> dict:
    case = _case(tmp_path)
    case["source"] = f"https://example.invalid/{suffix}"
    case["source_identity"] = {
        "kind": "url",
        "identity_sha256": hashlib.sha256(case["source"].encode("utf-8")).hexdigest(),
        "caption_sha256": (
            hashlib.sha256(expected_caption).hexdigest() if expected_caption is not None else None
        ),
    }
    case["environment"]["network_policy"] = "enabled"
    return case


def test_caption_expectation_matches_frozen_control_selected_subtitle(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    expected = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\ngood caption\n"
    receipt = control_harness.run_control(
        _url_case(tmp_path, "caption-good", expected), control, tmp_path / "out", tmp_path / "receipt", commit,
    )
    assert receipt["consumed_caption"] == {
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "selected_path": "call-1/video.en.vtt",
        "selected_sha256": hashlib.sha256(expected).hexdigest(),
    }
    assert (tmp_path / "receipt/caption-snapshots/call-1/video.en.vtt").is_file()


def test_no_caption_expectation_and_selected_caption_drift_refuse_with_receipt(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    no_caption = control_harness.run_control(
        _url_case(tmp_path, "no-caption", None), control, tmp_path / "no-caption-out", tmp_path / "no-caption-receipt", commit,
    )
    assert no_caption["consumed_caption"] == {
        "expected_sha256": None, "selected_path": None, "selected_sha256": None,
    }
    receipt_dir = tmp_path / "drift-receipt"
    with pytest.raises(control_harness.ControlIntegrityError, match="caption identity drifted"):
        control_harness.run_control(
            _url_case(
                tmp_path, "caption-drift",
                b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\ndrifted caption\n",
            ), control, tmp_path / "drift-out", receipt_dir, commit,
        )
    receipt = json.loads((receipt_dir / "run.json").read_text(encoding="utf-8"))
    assert receipt["control_clean_after"] is True
    assert receipt["consumed_caption"]["selected_path"] == "call-1/video.en.vtt"
    consumed = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\ngood caption\n"
    assert receipt["consumed_caption"]["selected_sha256"] == hashlib.sha256(consumed).hexdigest()
    assert b"drifted caption" in (tmp_path / "drift-out/download/video.en.vtt").read_bytes()


def test_timeout_terminates_descendant_process_group(tmp_path):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    case = _case(tmp_path)
    source = Path(case["source"])
    source.write_bytes(b"spawn-resistant-child")
    case["source_identity"]["identity_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    case["environment"]["timeout_seconds"] = 1
    receipt = control_harness.run_control(case, control, tmp_path / "out", tmp_path / "receipt", commit)
    assert receipt["timed_out"] is True
    time.sleep(2.2)
    assert not source.with_suffix(".child-survived").exists()


def test_git_checks_ignore_caller_repo_selection_environment(tmp_path, monkeypatch):
    repo, commit = _commit_control_fixture(tmp_path)
    control = control_harness.prepare_worktree(repo, tmp_path / "control", commit)
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / "index"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(decoy))
    control_harness.assert_clean_detached_control(control, commit)


def test_pair_order_is_stable_and_uses_both_first_positions():
    orders = {control_harness.paired_order(f"case-{index}") for index in range(128)}
    assert orders == {("control", "candidate"), ("candidate", "control")}
    assert control_harness.paired_order("case-17") == control_harness.paired_order("case-17")
