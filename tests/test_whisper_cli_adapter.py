"""whisper-cli: a real local speech model on any platform, no daemon, no network.

Before this, Linux had no local transcription option at all: local-http needs a
server the user must run themselves, and yap is macOS-only. A Linux user with no
server was pushed to cloud Whisper, which quietly contradicts the skill's
local-first promise. This adapter closes that gap with the pip-installable
`openai-whisper` CLI (detected, never installed).
"""
from __future__ import annotations

import subprocess

import pytest

import config
import transcription
import transcription_adapters as ta


# --- language mapping ---------------------------------------------------------
# openai-whisper takes bare codes and rejects locale forms -- the exact inverse
# of yap, which rejects bare codes. One WATCH_LANGUAGE value must satisfy both.

@pytest.mark.parametrize(
    "given,expected",
    [
        ("en", "en"),
        ("en-US", "en"),   # yap wants en_US here; whisper would reject it
        ("en_US", "en"),
        ("fr-FR", "fr"),
        ("auto", None),    # let whisper detect
    ],
)
def test_whisper_language_is_a_bare_code(given, expected):
    assert ta._whisper_language(given) == expected


def test_one_watch_language_satisfies_both_adapters():
    """The regression that motivates both mappings: WATCH_LANGUAGE=en must work
    on yap (needs en_US) AND whisper-cli (needs en)."""
    assert ta._yap_locale("en") == "en_US"
    assert ta._whisper_language("en") == "en"


# --- registration -------------------------------------------------------------

def test_whisper_cli_is_in_the_default_local_order_before_cloud():
    order = list(config.DEFAULT_STT_ORDER)
    assert "whisper-cli" in order
    # Local adapters must all precede any cloud adapter.
    for cloud in ("groq", "openai"):
        if cloud in order:
            assert order.index("whisper-cli") < order.index(cloud)


def test_adapter_registry_builds_whisper_cli():
    adapters = transcription.build_default_adapters(config.get_transcription_config())
    assert "whisper-cli" in adapters
    assert adapters["whisper-cli"].is_remote is False


# --- probe --------------------------------------------------------------------

def test_probe_reports_unavailable_when_binary_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(ta.shutil, "which", lambda _: None)
    adapter = ta.WhisperCliAdapter(executable="whisper")
    result = adapter.probe(None)
    assert result.available is False
    assert "not_installed" in (result.failure_code or "")


def test_probe_available_when_binary_present(monkeypatch):
    monkeypatch.setattr(ta.shutil, "which", lambda _: "/usr/local/bin/whisper")
    assert ta.WhisperCliAdapter().probe(None).available is True


# --- the exit-code trap -------------------------------------------------------

def test_success_requires_an_output_file_not_a_zero_exit(tmp_path, monkeypatch):
    """The whisper CLI can exit 0 having produced nothing (e.g. its internal
    ffmpeg fails on the input). Trusting the return code would report success
    with an empty transcript."""
    class Chunk:
        index = 0
        path = tmp_path / "chunk_000.wav"
        source_offset = 0.0
        duration = 1.0

    Chunk.path.write_bytes(b"")

    class Request:
        work_dir = tmp_path
        language = "auto"
        timeout = 5.0

    # Exit 0, but write no .srt.
    monkeypatch.setattr(
        ta.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0, "", ""),
    )
    adapter = ta.WhisperCliAdapter()
    with pytest.raises(RuntimeError, match="did not produce an output file"):
        adapter._transcribe_one(Request(), Chunk())


def test_stale_output_from_a_killed_run_is_not_mistaken_for_success(tmp_path, monkeypatch):
    """A prior killed run can leave an .srt behind. If the next invocation
    produces nothing, that stale file must not be read as this run's result."""
    class Chunk:
        index = 0
        path = tmp_path / "chunk_000.wav"
        source_offset = 0.0
        duration = 1.0

    Chunk.path.write_bytes(b"")

    class Request:
        work_dir = tmp_path
        language = "auto"
        timeout = 5.0

    stale_dir = tmp_path / "whisper-cli"
    stale_dir.mkdir()
    stale = stale_dir / "chunk_000.srt"
    stale.write_text("1\n00:00:00,000 --> 00:00:01,000\nstale text from a dead run\n")

    monkeypatch.setattr(
        ta.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0, "", ""),
    )
    with pytest.raises(RuntimeError, match="did not produce an output file"):
        ta.WhisperCliAdapter()._transcribe_one(Request(), Chunk())


# --- timeout ------------------------------------------------------------------

def test_default_timeout_fits_a_full_chunk_on_a_slow_cpu():
    """Chunks are ~3.3 min of audio. Measured 93s (0.46x realtime) on Apple
    Silicon faster-whisper, but CPU-only openai-whisper -- the hardware this
    adapter exists for -- runs slower than realtime. 300s would time out there."""
    cfg = config.get_transcription_config()
    assert cfg["timeout"] >= 600.0


# --- R2a-2: Silero VAD tier (whisper-cli only, detect-never-download) ----------
#
# Best-effort and fail-open: the VAD flags are composed ONLY when the model
# file already exists on disk and config allows it. A failing --vad run falls
# back to a plain run so VAD can never cost a transcript.

import json


def _vad_fixtures(tmp_path):
    class Chunk:
        index = 0
        path = tmp_path / "chunk_000.wav"
        source_offset = 0.0
        duration = 1.0

    Chunk.path.write_bytes(b"")

    class Request:
        work_dir = tmp_path
        language = "auto"
        timeout = 5.0

    return Chunk(), Request()


def _fake_run_writing_json(tmp_path, commands, *, fail_when_vad=False):
    def fake_run(command, **kwargs):
        commands.append(list(command))
        if fail_when_vad and "--vad" in command:
            return subprocess.CompletedProcess(command, 1, "", "vad failed")
        out_dir = tmp_path / "whisper-cli"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "chunk_000.json").write_text(
            json.dumps({"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    return fake_run


def test_vad_flags_never_composed_after_withdrawal(tmp_path, monkeypatch):
    """1.2.1: the 1.2.0 VAD tier composed whisper.cpp flags against the pip
    openai-whisper CLI — it could never engage and the fail-open catch hid it
    (L6 review, three independent angles). Withdrawn until composed against a
    capability-probed CLI that supports it."""
    model = tmp_path / "ggml-silero-v5.1.2.bin"
    model.write_bytes(b"x")
    adapter = ta.WhisperCliAdapter(vad=True, vad_model_path=str(model))
    assert adapter._vad_args() == []



def test_absent_model_file_means_no_vad_flags(tmp_path, monkeypatch):
    chunk, request = _vad_fixtures(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(ta.subprocess, "run", _fake_run_writing_json(tmp_path, commands))
    adapter = ta.WhisperCliAdapter(vad=True, vad_model_path=str(tmp_path / "missing.bin"))
    adapter._transcribe_one(request, chunk)
    assert "--vad" not in commands[0]


def test_vad_off_config_wins_even_with_model_present(tmp_path, monkeypatch):
    chunk, request = _vad_fixtures(tmp_path)
    model = tmp_path / "silero.bin"
    model.write_bytes(b"model")
    commands: list[list[str]] = []
    monkeypatch.setattr(ta.subprocess, "run", _fake_run_writing_json(tmp_path, commands))
    adapter = ta.WhisperCliAdapter(vad=False, vad_model_path=str(model))
    adapter._transcribe_one(request, chunk)
    assert "--vad" not in commands[0]



def test_registry_still_accepts_vad_config_keys():
    """Config keys survive as documented-future; wiring them must not crash."""
    adapters = transcription.build_default_adapters(config.get_transcription_config())
    assert "whisper-cli" in adapters


