"""Focused P11/P16 tests for the normalized transcription Interface."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
import transcription
from transcription import (
    AdapterAvailability,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionPipeline,
    TranscriptionRequest,
)
from transcription_adapters import SidecarAdapter


class ExplodingAdapter:
    requires_audio = False
    is_remote = False

    def __init__(self, name: str):
        self.name = name
        self.probed = False

    def probe(self, request):
        self.probed = True
        raise AssertionError(f"{self.name} must not be probed")

    def transcribe(self, request, receipts):
        raise AssertionError(f"{self.name} must not execute")


def _request(tmp_path: Path, **values) -> TranscriptionRequest:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    defaults = {
        "media_path": media,
        "work_dir": tmp_path / "work",
        "adapter_order": (),
        "config": {"receipts": False},
    }
    defaults.update(values)
    return TranscriptionRequest(**defaults)


def test_result_contract_is_json_serializable_and_validated():
    segment = TranscriptSegment(
        start=1.0, end=2.0, text="hello", language="en", adapter="sidecar", model="vtt"
    )
    result = TranscriptResult(state="success", segments=(segment,), adapter="sidecar")
    assert result.usable is True
    assert json.loads(result.to_json())["segments"][0]["adapter"] == "sidecar"
    with pytest.raises(ValueError):
        TranscriptResult(state="success")
    with pytest.raises(ValueError):
        TranscriptSegment(start=3, end=2, text="bad")


def test_native_segments_short_circuit_every_adapter(tmp_path):
    sidecar = ExplodingAdapter("sidecar")
    request = _request(
        tmp_path,
        native_segments=({"start": 2.0, "end": 3.0, "text": "native"},),
        adapter_order=("groq",),
        allow_remote=True,
    )
    result = TranscriptionPipeline({"sidecar": sidecar}).run(request)
    assert result.state == "success"
    assert result.adapter == "native-captions"
    assert result.segments[0].text == "native"
    assert sidecar.probed is False


def test_sidecar_short_circuits_later_asr(tmp_path):
    request = _request(tmp_path, adapter_order=("groq",), allow_remote=True)
    request.media_path.with_suffix(".vtt").write_text(
        "WEBVTT\n\n00:01.000 --> 00:02.000\nsidecar text\n",
        encoding="utf-8",
    )
    cloud = ExplodingAdapter("groq")
    result = TranscriptionPipeline({"sidecar": SidecarAdapter(), "groq": cloud}).run(request)
    assert result.state == "success"
    assert result.adapter == "sidecar"
    assert result.segments[0].start == 1.0
    assert cloud.probed is False


def test_remote_adapter_is_not_probed_without_authorization(tmp_path):
    cloud = ExplodingAdapter("groq")
    cloud.is_remote = True

    class MissingSidecar:
        name = "sidecar"
        requires_audio = False
        is_remote = False

        def probe(self, request):
            return AdapterAvailability(False, "sidecar_not_found")

    result = TranscriptionPipeline({"sidecar": MissingSidecar(), "groq": cloud}).run(
        _request(tmp_path, adapter_order=("groq",), allow_remote=False)
    )
    assert result.state == "unavailable"
    assert result.attempts[-1].failure_code == "remote_not_authorized"
    assert cloud.probed is False


def test_transcription_config_and_diagnostics_are_host_independent(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    for name in (
        "WATCH_STT_ORDER", "WATCH_STT_URL", "WATCH_STT_MODEL", "WATCH_LANGUAGE",
        "WATCH_STT_ALLOW_REMOTE", "WATCH_STT_MAX_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)
    resolved = config.get_transcription_config(
        WATCH_STT_ORDER="yap,groq",
        WATCH_LANGUAGE="en",
        WATCH_STT_ALLOW_REMOTE="true",
        WATCH_STT_MAX_ATTEMPTS="3",
    )
    assert resolved["order"] == ("yap", "groq")
    assert resolved["language"] == "en"
    assert resolved["allow_remote"] is True
    assert resolved["max_attempts"] == 3

    diagnostics = transcription.transcription_diagnostics(
        WATCH_STT_ORDER="local-http,yap", WATCH_STT_ALLOW_REMOTE=False
    )
    assert diagnostics["state"] == "success"
    assert diagnostics["local_http"]["loopback_required"] is True
    assert diagnostics["yap"]["auto_install"] is False
    assert "GROQ_API_KEY" not in json.dumps(diagnostics)


def test_invalid_adapter_order_is_a_stable_config_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    diagnostics = transcription.transcription_diagnostics(WATCH_STT_ORDER="remote-magic")
    assert diagnostics["state"] == "fatal"
    assert diagnostics["failure_code"] == "invalid_config"
