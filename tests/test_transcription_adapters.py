"""Focused P12-P15 Adapter tests with no live network or cloud calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import transcription_adapters as adapters
from transcription import TranscriptionRequest
from transcription_adapters import CloudWhisperAdapter, LoopbackHTTPAdapter, SidecarAdapter, YapAdapter
from transcription_chunks import AudioChunk, ChunkReceiptStore, PreparedAudio


def _prepared_request(tmp_path: Path, *, allow_remote: bool = False) -> TranscriptionRequest:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = AudioChunk(index=0, path=audio, source_offset=30.0, duration=5.0, sha256="abc")
    return TranscriptionRequest(
        media_path=media,
        work_dir=tmp_path / "work",
        adapter_order=(),
        allow_remote=allow_remote,
        config={"receipts": False},
        prepared_audio=PreparedAudio(audio, (chunk,), 30.0, 35.0),
    )


def test_same_basename_srt_is_normalized(tmp_path):
    request = _prepared_request(tmp_path)
    request.media_path.with_suffix(".srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nhello srt\n",
        encoding="utf-8",
    )
    adapter = SidecarAdapter()
    assert adapter.probe(request).available is True
    result = adapter.transcribe(request, ChunkReceiptStore(tmp_path / "off", enabled=False))
    assert result.state == "success"
    assert result.model == "srt"
    assert result.segments[0].text == "hello srt"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:8082",
        "http://localhost.evil:8082",
        "http://127.0.0.1.evil:8082",
        "http://user:secret@127.0.0.1:8082",
    ],
)
def test_loopback_adapter_rejects_every_remote_or_credentialed_url(url):
    with pytest.raises(ValueError):
        adapters._loopback_endpoint(url)


def test_loopback_endpoint_supports_default_8082_shape():
    transcription_url, models_url = adapters._loopback_endpoint("http://127.0.0.1:8082")
    assert transcription_url == "http://127.0.0.1:8082/v1/audio/transcriptions"
    assert models_url == "http://127.0.0.1:8082/v1/models"


def test_loopback_probe_is_mocked_and_never_contacts_remote(monkeypatch, tmp_path):
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(request, timeout):
        seen.append(request.full_url)
        return Response()

    # Loopback requests go through a redirect-refusing opener, not urlopen: a
    # hostile local server must not be able to 302 the audio off the machine.
    monkeypatch.setattr(adapters._LOOPBACK_OPENER, "open", fake_open)
    adapter = LoopbackHTTPAdapter(url="http://[::1]:8082", model="local", probe_timeout=0.1)
    assert adapter.probe(_prepared_request(tmp_path)).available is True
    assert seen == ["http://[::1]:8082/v1/models"]


def test_yap_absent_is_silent_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapters.shutil, "which", lambda name: None)
    availability = YapAdapter().probe(_prepared_request(tmp_path))
    assert availability.available is False
    assert availability.failure_code == "yap_not_installed"


def test_yap_present_returns_absolute_timestamped_segments(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapters.shutil, "which", lambda name: "/opt/homebrew/bin/yap")

    class Result:
        returncode = 0
        stdout = "WEBVTT\n\n00:01.000 --> 00:02.000\nlocal words\n"
        stderr = ""

    commands = []
    monkeypatch.setattr(
        adapters.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or Result(),
    )
    request = _prepared_request(tmp_path)
    adapter = YapAdapter()
    result = adapter.transcribe(request, ChunkReceiptStore(tmp_path / "off", enabled=False))
    assert result.state == "success"
    assert result.segments[0].start == 31.0
    assert commands[0][:2] == ["yap", "transcribe"]
    assert "--vtt" in commands[0]


def test_cloud_adapter_requires_authorization_before_key_lookup(monkeypatch, tmp_path):
    called = False

    def explode(preferred):
        nonlocal called
        called = True
        raise AssertionError("key lookup should not occur")

    monkeypatch.setattr(adapters.whisper, "load_api_key", explode)
    availability = CloudWhisperAdapter("groq").probe(_prepared_request(tmp_path, allow_remote=False))
    assert availability.failure_code == "remote_not_authorized"
    assert called is False


def test_authorized_cloud_adapter_uses_bounded_normalized_call(monkeypatch, tmp_path):
    request = _prepared_request(tmp_path, allow_remote=True)
    monkeypatch.setattr(adapters.whisper, "load_api_key", lambda preferred: (preferred, "secret"))
    calls = []

    def fake_transcribe(backend, key, path, **kwargs):
        calls.append((backend, key, path, kwargs))
        return [{"start": 0.5, "end": 1.5, "text": "cloud words"}]

    monkeypatch.setattr(adapters.whisper, "transcribe_file", fake_transcribe)
    result = CloudWhisperAdapter("groq").transcribe(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False)
    )
    assert result.state == "success"
    assert result.segments[0].start == 30.5
    assert result.diagnostics["remote_transmission"] is True
    assert calls[0][3]["max_attempts"] == 1
    assert "secret" not in json.dumps(result.to_dict())
