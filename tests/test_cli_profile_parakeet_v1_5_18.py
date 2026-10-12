"""Opt-in parakeet-mlx profile for the whisper-cli adapter (v1.5.18).

Parakeet runs on the MLX GPU, so it is NEVER auto-selected: only
WATCH_WHISPER_CLI_PROFILE=parakeet turns it on. A fake executable written into
tmp_path stands in for parakeet-mlx (no GPU, no model, no network).
"""
from __future__ import annotations

import json
import stat
import sys

import pytest

import config
import transcription
import transcription_adapters as ta


class _Chunk:
    index = 0
    source_offset = 0.0
    duration = 1.0

    def __init__(self, tmp_path):
        self.path = tmp_path / "chunk_000.wav"
        self.path.write_bytes(b"")


class _Request:
    language = "fr"
    timeout = 5.0

    def __init__(self, tmp_path):
        self.work_dir = tmp_path


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path_factory.mktemp("cfg") / "watch")


def _fake_parakeet(tmp_path, *, write_output=True):
    """Executable that records argv and writes canned parakeet-mlx JSON."""
    exe = tmp_path / "parakeet-mlx"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "a = sys.argv[1:]\n"
        "pathlib.Path(__file__).with_name('argv.json').write_text(json.dumps(a))\n"
        f"if {write_output!r}:\n"
        "    out = pathlib.Path(a[a.index('--output-dir') + 1])\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    (out / (pathlib.Path(a[0]).stem + '.json')).write_text(json.dumps({'text': 'Bonjour le monde. Ca va.', 'sentences': [\n"
        "        {'text': ' Bonjour le monde.', 'start': 0.0, 'end': 1.5, 'tokens': []},\n"
        "        {'text': ' Ca va.', 'start': 1.5, 'end': 2.0, 'tokens': []}]}))\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def test_default_config_is_whisper_profile_and_never_parakeet():
    cfg = config.get_transcription_config()
    assert cfg["whisper_cli_profile"] == "whisper"
    assert cfg["whisper_cli_path"] == "whisper"
    adapter = transcription.build_default_adapters(cfg)["whisper-cli"]
    assert adapter.profile == "whisper"


def test_profile_selected_only_when_opted_in(monkeypatch):
    monkeypatch.setenv("WATCH_WHISPER_CLI_PROFILE", "parakeet")
    cfg = config.get_transcription_config()
    assert cfg["whisper_cli_path"] == "parakeet-mlx"  # profile default binary
    assert transcription.build_default_adapters(cfg)["whisper-cli"].profile == "parakeet"


def test_unknown_profile_is_rejected(monkeypatch):
    monkeypatch.setenv("WATCH_WHISPER_CLI_PROFILE", "bogus")
    with pytest.raises(ValueError, match="WATCH_WHISPER_CLI_PROFILE"):
        config.get_transcription_config()


def test_not_in_default_order_and_no_new_adapter():
    assert "parakeet" not in " ".join(config.DEFAULT_STT_ORDER)
    assert "parakeet" not in config.STT_ADAPTERS


def test_command_line_and_json_parsing(tmp_path):
    exe = _fake_parakeet(tmp_path)
    adapter = ta.WhisperCliAdapter(executable=str(exe), profile="parakeet")
    segs = adapter._transcribe_one(_Request(tmp_path), _Chunk(tmp_path))
    argv = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert argv == [
        str(tmp_path / "chunk_000.wav"),
        "--output-dir", str(tmp_path / "whisper-cli"),
        "--output-format", "json",
        "--chunk-duration", "120",
    ]
    # WATCH_LANGUAGE ("fr") is deliberately not passed; neither is the whisper default model.
    assert "--language" not in argv and "--model" not in argv
    assert [(s["start"], s["end"], s["text"].strip()) for s in segs] == [
        (0.0, 1.5, "Bonjour le monde."),
        (1.5, 2.0, "Ca va."),
    ]


def test_explicit_model_is_passed(tmp_path):
    exe = _fake_parakeet(tmp_path)
    adapter = ta.WhisperCliAdapter(executable=str(exe), model="mlx-community/x", profile="parakeet")
    adapter._transcribe_one(_Request(tmp_path), _Chunk(tmp_path))
    argv = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert argv[argv.index("--model") + 1] == "mlx-community/x"


def test_missing_output_is_adapter_failure(tmp_path):
    """Exit 0 with no JSON must fail the chunk (so the chain falls through)."""
    exe = _fake_parakeet(tmp_path, write_output=False)
    adapter = ta.WhisperCliAdapter(executable=str(exe), profile="parakeet")
    with pytest.raises(RuntimeError, match="did not produce an output file"):
        adapter._transcribe_one(_Request(tmp_path), _Chunk(tmp_path))


@pytest.mark.parametrize("model", ["medium", "turbo", "large-v3"])
def test_whisper_model_names_are_not_passed_to_parakeet(tmp_path, model):
    """An old .env with WATCH_WHISPER_CLI_MODEL=medium must not break parakeet."""
    exe = _fake_parakeet(tmp_path)
    adapter = ta.WhisperCliAdapter(executable=str(exe), model=model, profile="parakeet")
    adapter._transcribe_one(_Request(tmp_path), _Chunk(tmp_path))
    argv = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert "--model" not in argv


def test_gpu_lock_blocks_second_holder(tmp_path):
    import fcntl
    with ta._mlx_gpu_lock(1.0):
        path = ta._mlx_gpu_lock_path()
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        with open(path, "a") as other:  # separate open file description
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(path, "a") as other:  # released on exit
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_gpu_lock_busy_fails_adapter_cleanly(tmp_path, monkeypatch):
    exe = _fake_parakeet(tmp_path)
    monkeypatch.setattr(ta, "GPU_LOCK_WAIT", 0.3)
    adapter = ta.WhisperCliAdapter(executable=str(exe), profile="parakeet")
    with ta._mlx_gpu_lock(1.0):
        with pytest.raises(RuntimeError, match="GPU lock busy"):
            adapter._transcribe_one(_Request(tmp_path), _Chunk(tmp_path))
    assert not (tmp_path / "argv.json").exists()  # parakeet never launched


def test_timeout_uses_config_value(tmp_path, monkeypatch):
    exe = _fake_parakeet(tmp_path)
    seen = {}
    real = ta.subprocess.run

    def spy(*a, **kw):
        seen["timeout"] = kw.get("timeout")
        return real(*a, **kw)

    monkeypatch.setattr(ta.subprocess, "run", spy)
    monkeypatch.setattr(config, "WHISPER_CLI_TIMEOUT", 4321)
    ta.WhisperCliAdapter(executable=str(exe), profile="parakeet")._transcribe_one(
        _Request(tmp_path), _Chunk(tmp_path))
    assert seen["timeout"] == 4321
