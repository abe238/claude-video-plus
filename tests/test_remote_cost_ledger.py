"""v1.5.3 A1: cumulative remote transcription cost bound (credit vcolombo).

The per-chunk MAX_UPLOAD_BYTES cap bounds one upload; the RemoteCostLedger
bounds the RUN — cumulative wire bytes and send attempts, shared across Groq
and OpenAI, charged before every HTTP send including retries and failures.
No test here touches the network.
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

import whisper
from transcription import TranscriptionPipeline, TranscriptionRequest
from transcription_adapters import CloudWhisperAdapter
from transcription_chunks import AudioChunk, ChunkReceiptStore, PreparedAudio
from whisper import RemoteCostExceeded, RemoteCostLedger


# --- ledger unit behavior -------------------------------------------------


def test_exact_bound_is_accepted_and_next_send_refused():
    ledger = RemoteCostLedger(max_bytes=100, max_attempts=0)
    ledger.charge(60)
    ledger.charge(40)  # lands exactly on the cap: allowed...
    assert ledger.spent_bytes == 100
    # ...and LATCHES immediately: the pipeline gate keys off `exhausted`, so a
    # ledger-unaware remote adapter must be refused after a fully-spent budget
    # even though no charge ever went over.
    assert ledger.exhausted is True
    with pytest.raises(RemoteCostExceeded):
        ledger.charge(1)


def test_exact_cap_latches_and_short_circuits_next_remote_adapter(tmp_path, monkeypatch):
    """Regression for the exact-cap bypass: ONE send consuming the whole
    budget must leave the ledger exhausted so a following ledger-unaware
    remote adapter is never probed."""
    request = _many_chunk_request(
        tmp_path, 1, adapter_order=("groq", "remote-spy"), max_attempts=1
    )
    request.remote_ledger.max_bytes = 50  # exactly one 50-byte send
    request.remote_ledger.max_attempts = 0
    calls = {"n": 0}

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        calls["n"] += 1
        ledger.charge(50)  # exact cap — allowed, then latched
        return []  # the send spent the budget but produced nothing usable

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    spy = _ExplodingRemoteSpy()
    result = TranscriptionPipeline(
        {"sidecar": _NoSidecar(), "groq": CloudWhisperAdapter("groq"), "remote-spy": spy}
    ).run(request)
    assert calls["n"] == 1  # a single first-adapter attempt, no retries
    # Before the latch fix this reproduced: exhausted=False, spy probed+ran.
    assert spy.probed is False
    assert request.remote_ledger.exhausted is True
    spy_attempts = [a for a in result.attempts if a.adapter == "remote-spy"]
    assert spy_attempts and spy_attempts[0].failure_code == "remote_cost_limit_exceeded"


def test_exact_cap_failure_still_reports_cost_limit_single_provider(tmp_path, monkeypatch):
    """Exact-cap edge with NO later remote adapter: the last permitted send
    consumed the budget and failed, so RemoteCostExceeded never fired — the
    run must still classify as cost-limited, not generic unavailable."""
    request = _many_chunk_request(tmp_path, 1, adapter_order=("groq",), max_attempts=1)
    request.remote_ledger.max_bytes = 50
    request.remote_ledger.max_attempts = 0

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)  # exact cap, latches
        raise SystemExit("HTTP 500")  # ...and the send then failed

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    result = TranscriptionPipeline(
        {"sidecar": _NoSidecar(), "groq": CloudWhisperAdapter("groq")}
    ).run(request)
    assert result.state == "unavailable"
    assert result.failure_code == "remote_cost_limit_exceeded"
    assert whisper.REMOTE_COST_GUIDANCE in result.warnings
    assert result.diagnostics["remote_transmission"] is True


def test_attempt_bound_trips_independently_of_bytes():
    ledger = RemoteCostLedger(max_bytes=0, max_attempts=2)
    ledger.charge(10)
    ledger.charge(10)
    with pytest.raises(RemoteCostExceeded):
        ledger.charge(10)


def test_exhausted_latches_for_the_rest_of_the_run():
    ledger = RemoteCostLedger(max_bytes=10, max_attempts=0)
    with pytest.raises(RemoteCostExceeded):
        ledger.charge(11)
    # Even a tiny later send must be refused: the run's budget is spent.
    with pytest.raises(RemoteCostExceeded):
        ledger.charge(1)


def test_zero_disables_each_bound():
    ledger = RemoteCostLedger(max_bytes=0, max_attempts=0)
    for _ in range(500):
        ledger.charge(10 * 1024 * 1024)
    assert ledger.exhausted is False


def test_env_defaults_and_malformed_env(monkeypatch):
    monkeypatch.delenv("WATCH_REMOTE_MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("WATCH_REMOTE_MAX_ATTEMPTS", raising=False)
    ledger = RemoteCostLedger()
    assert ledger.max_bytes == whisper.DEFAULT_REMOTE_MAX_UPLOAD_BYTES
    assert ledger.max_attempts == whisper.DEFAULT_REMOTE_MAX_ATTEMPTS

    monkeypatch.setenv("WATCH_REMOTE_MAX_UPLOAD_MB", "banana")
    monkeypatch.setenv("WATCH_REMOTE_MAX_ATTEMPTS", "-5")
    ledger = RemoteCostLedger()
    assert ledger.max_bytes == whisper.DEFAULT_REMOTE_MAX_UPLOAD_BYTES
    assert ledger.max_attempts == whisper.DEFAULT_REMOTE_MAX_ATTEMPTS

    monkeypatch.setenv("WATCH_REMOTE_MAX_UPLOAD_MB", "0")
    monkeypatch.setenv("WATCH_REMOTE_MAX_ATTEMPTS", "0")
    ledger = RemoteCostLedger()
    assert ledger.max_bytes == 0
    assert ledger.max_attempts == 0

    monkeypatch.setenv("WATCH_REMOTE_MAX_UPLOAD_MB", "3")
    ledger = RemoteCostLedger()
    assert ledger.max_bytes == 3 * 1024 * 1024


# --- charge sits at the HTTP send chokepoint ------------------------------


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


def test_post_whisper_charges_every_attempt_including_failures(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 100)
    calls = {"n": 0}

    def failing_urlopen(request, timeout, context):
        calls["n"] += 1
        raise _http_error(500)

    monkeypatch.setattr(whisper, "urlopen", failing_urlopen)
    monkeypatch.setattr(whisper.time, "sleep", lambda s: None)
    ledger = RemoteCostLedger(max_bytes=0, max_attempts=0)
    with pytest.raises(SystemExit):
        whisper._post_whisper(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            "k", "m", audio, max_attempts=3, ledger=ledger,
        )
    assert calls["n"] == 3
    # Every attempt charged the same wire payload, failures included.
    assert ledger.attempts == 3
    assert ledger.spent_bytes > 3 * 100  # multipart body > raw audio bytes


def test_post_whisper_refuses_before_sending_when_exhausted(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 100)

    def must_not_send(request, timeout, context):
        raise AssertionError("HTTP send happened past the cost bound")

    monkeypatch.setattr(whisper, "urlopen", must_not_send)
    ledger = RemoteCostLedger(max_bytes=1, max_attempts=0)
    with pytest.raises(RemoteCostExceeded):
        whisper._post_whisper(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            "k", "m", audio, max_attempts=2, ledger=ledger,
        )


def test_no_ledger_means_no_bound_for_direct_unit_callers(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    payload = {"text": "hi", "segments": [{"start": 0, "end": 1, "text": "hi"}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(whisper, "urlopen", lambda *a, **k: _Resp())
    out = whisper._post_whisper("https://e", "k", "m", audio, max_attempts=1)
    assert out["text"] == "hi"


# --- adapter + pipeline integration ---------------------------------------


def _many_chunk_request(tmp_path: Path, count: int, **values) -> TranscriptionRequest:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    chunks = []
    for i in range(count):
        audio = tmp_path / f"chunk{i}.mp3"
        audio.write_bytes(b"a" * 50)
        chunks.append(
            AudioChunk(index=i, path=audio, source_offset=float(i * 5), duration=5.0, sha256=f"c{i}")
        )
    defaults = {
        "media_path": media,
        "work_dir": tmp_path / "work",
        "adapter_order": (),
        "allow_remote": True,
        "config": {"receipts": False},
        "prepared_audio": PreparedAudio(chunks[0].path, tuple(chunks), 0.0, count * 5.0),
    }
    defaults.update(values)
    return TranscriptionRequest(**defaults)


def test_cost_trip_stops_all_further_sends_and_keeps_completed_chunks(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 4)
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 2
    sends = {"n": 0}

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)
        sends["n"] += 1
        return [{"start": 0.0, "end": 1.0, "text": f"seg {sends['n']}"}]

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    adapter = CloudWhisperAdapter("groq")
    result = adapter.transcribe(request, ChunkReceiptStore(tmp_path / "off", enabled=False))

    assert sends["n"] == 2  # third charge refused BEFORE any send
    assert result.state == "partial"
    assert result.failure_code == "remote_cost_limit_exceeded"
    assert len(result.segments) == 2
    assert any("cost bound" in w for w in result.warnings)
    assert result.diagnostics["remote_transmission"] is True


def test_failed_uploads_still_report_remote_transmission(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 1)

    def failing_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)  # the upload went out...
        raise SystemExit("HTTP 500")  # ...and then failed

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", failing_transcribe_file)
    adapter = CloudWhisperAdapter("groq")
    result = adapter.transcribe(request, ChunkReceiptStore(tmp_path / "off", enabled=False))
    assert result.state == "unavailable"
    # The old processed>0 rule reported False here — bytes DID leave the machine.
    assert result.diagnostics["remote_transmission"] is True


def test_pending_receipts_flush_on_cost_escape(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 3, config={"receipts": True})
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 2

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)
        return [{"start": 0.0, "end": 1.0, "text": "banked"}]

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    adapter = CloudWhisperAdapter("groq")
    store_path = tmp_path / "work" / "receipts.json"
    store = ChunkReceiptStore(store_path, enabled=True)
    result = adapter.transcribe(request, store)
    assert result.failure_code == "remote_cost_limit_exceeded"
    # The two completed (paid-for) chunks reached disk despite the early
    # escape. Positive control: puts are batched (threshold 5), so without
    # the finally-flush this file would not exist at all.
    persisted = json.loads(store_path.read_text())
    assert len(persisted["entries"]) == 2


def test_second_provider_shares_the_spent_budget(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 1)
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 1
    request.remote_ledger.attempts = 1  # groq already spent the run's budget
    request.remote_ledger.exhausted = True

    adapter = CloudWhisperAdapter("openai")
    availability = adapter.probe(request)
    assert availability.available is False
    assert availability.failure_code == "remote_cost_limit_exceeded"


def test_pipeline_preserves_cost_code_when_no_fallback_remains(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 2, adapter_order=("groq", "openai"))
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 1
    request = __import__("dataclasses").replace(request, require_complete=True)
    backends_called: list[str] = []

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        backends_called.append(backend)
        ledger.charge(50)
        raise SystemExit("HTTP 500")

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    result = TranscriptionPipeline(
        {
            "sidecar": _NoSidecar(),
            "groq": CloudWhisperAdapter("groq"),
            "openai": CloudWhisperAdapter("openai"),
        }
    ).run(request)
    assert result.state == "unavailable"
    assert result.failure_code == "remote_cost_limit_exceeded"
    assert whisper.REMOTE_COST_GUIDANCE in result.warnings
    assert result.diagnostics["remote_transmission"] is True
    # One shared ledger: groq's allowed attempt (plus the retry that tripped
    # the bound before sending) spent it, and openai never reached its
    # transcribe path at all.
    assert "openai" not in backends_called
    openai_attempts = [a for a in result.attempts if a.adapter == "openai"]
    assert openai_attempts and openai_attempts[0].failure_code == "remote_cost_limit_exceeded"


class _ExplodingRemoteSpy:
    """A remote adapter that does not check the ledger itself: the PIPELINE
    must refuse it after exhaustion — no probe, no transcribe."""

    requires_audio = False
    is_remote = True
    name = "remote-spy"

    def __init__(self):
        self.probed = False

    def probe(self, request):
        self.probed = True
        raise AssertionError("remote adapter probed after budget exhaustion")

    def transcribe(self, request, receipts):  # pragma: no cover
        raise AssertionError("remote adapter executed after budget exhaustion")


def test_pipeline_short_circuits_any_remote_adapter_after_exhaustion(tmp_path, monkeypatch):
    request = _many_chunk_request(tmp_path, 1, adapter_order=("groq", "remote-spy"))
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 1

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)
        raise SystemExit("HTTP 500")

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    spy = _ExplodingRemoteSpy()
    result = TranscriptionPipeline(
        {"sidecar": _NoSidecar(), "groq": CloudWhisperAdapter("groq"), "remote-spy": spy}
    ).run(request)
    assert spy.probed is False
    spy_attempts = [a for a in result.attempts if a.adapter == "remote-spy"]
    assert spy_attempts and spy_attempts[0].failure_code == "remote_cost_limit_exceeded"


def test_local_partial_after_cost_trip_keeps_cost_code_and_full_attempts(tmp_path, monkeypatch):
    """Locals run before cloud by default: a stored local partial predates the
    cost trip, so the final result must re-attach the full attempt list and
    surface the run-level cost code, not rewrite it to incomplete_chunks."""
    from transcription import AdapterAvailability, TranscriptResult, TranscriptSegment

    class _PartialLocal:
        requires_audio = False
        is_remote = False
        name = "locallike"

        def probe(self, request):
            return AdapterAvailability(True)

        def transcribe(self, request, receipts):
            return TranscriptResult(
                state="partial",
                segments=(
                    TranscriptSegment(start=0.0, end=1.0, text="half", adapter="locallike"),
                ),
                adapter="locallike",
                failure_code="incomplete_chunks",
            )

    request = _many_chunk_request(tmp_path, 2, adapter_order=("locallike", "groq"))
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 1

    def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
        ledger.charge(50)
        raise SystemExit("HTTP 500")

    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
    monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
    result = TranscriptionPipeline(
        {"sidecar": _NoSidecar(), "locallike": _PartialLocal(), "groq": CloudWhisperAdapter("groq")}
    ).run(request)
    assert result.state == "partial"
    assert result.failure_code == "remote_cost_limit_exceeded"
    assert whisper.REMOTE_COST_GUIDANCE in result.warnings
    assert result.diagnostics["remote_transmission"] is True
    assert any(a.adapter == "groq" for a in result.attempts)


def test_exact_multipart_byte_accounting(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 1000)
    seen = {}
    payload = {"text": "hi", "segments": [{"start": 0, "end": 1, "text": "hi"}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    def capturing_urlopen(request, timeout, context):
        seen["wire_bytes"] = len(request.data)
        return _Resp()

    monkeypatch.setattr(whisper, "urlopen", capturing_urlopen)
    ledger = RemoteCostLedger(max_bytes=0, max_attempts=0)
    whisper._post_whisper("https://e", "k", "m", audio, max_attempts=1, ledger=ledger)
    assert ledger.attempts == 1
    assert ledger.spent_bytes == seen["wire_bytes"]


def test_focused_range_fits_a_budget_the_full_file_exceeds(tmp_path, monkeypatch, audio_clip):
    """The acceptance the guidance promises: real ffmpeg range extraction and
    REAL transcribe_file → _post_whisper wire accounting. A cap sized between
    the focused upload and the full-file upload lets the --start/--end run
    complete while the full-file run is refused before any send."""
    from transcription_chunks import prepare_audio

    payload = {"text": "tone", "segments": [{"start": 0, "end": 1, "text": "tone"}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    wire: list[int] = []

    def capturing_urlopen(request, timeout, context):
        wire.append(len(request.data))
        return _Resp()

    monkeypatch.setattr(whisper, "urlopen", capturing_urlopen)
    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))

    prepared = prepare_audio(
        audio_clip, tmp_path / "prep", start_seconds=0.5, end_seconds=1.5
    )
    if all(getattr(c, "silent", False) for c in prepared.chunks):
        pytest.skip("silence classifier flagged the tone; range test needs speech chunks")
    full_audio = tmp_path / "prep-full"
    prepared_full = prepare_audio(audio_clip, full_audio)
    full_bytes = sum(
        c.path.stat().st_size for c in prepared_full.chunks if not getattr(c, "silent", False)
    )

    # Focused run: REAL sends through _post_whisper, wire bytes captured.
    request = _many_chunk_request(tmp_path, 1, prepared_audio=prepared)
    request.remote_ledger.max_bytes = 0
    request.remote_ledger.max_attempts = 0
    result = CloudWhisperAdapter("groq").transcribe(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False)
    )
    assert result.state == "success"
    focused_wire_total = sum(wire)
    assert request.remote_ledger.spent_bytes == focused_wire_total
    assert result.diagnostics["source_range"] == [prepared.source_start, prepared.source_end]
    # The extraction is a genuine cut: the full file's audio outweighs the
    # focused range's (2s of tone vs the extracted ~1s).
    focused_bytes = sum(
        c.path.stat().st_size for c in prepared.chunks if not getattr(c, "silent", False)
    )
    assert full_bytes > focused_bytes

    # Negative control: the FULL file against a cap the focused run fit.
    # multipart(full audio) > multipart(focused range) > cap forbids nothing
    # focused, everything full — refused BEFORE urlopen.
    cap = focused_wire_total  # focused landed exactly on/under this
    sends_before = len(wire)

    def must_not_send(request, timeout, context):
        raise AssertionError("full-file upload went out past the cost bound")

    monkeypatch.setattr(whisper, "urlopen", must_not_send)
    full_speech = [c for c in prepared_full.chunks if not getattr(c, "silent", False)]
    ledger = RemoteCostLedger(max_bytes=cap, max_attempts=0)
    ledger.spent_bytes = 0
    with pytest.raises((RemoteCostExceeded, SystemExit)):
        for chunk in full_speech:
            whisper.transcribe_file("groq", "k", chunk.path, language="auto", ledger=ledger)
    assert len(wire) == sends_before  # not one full-file byte hit the wire


def _loopback_server(payload: dict):
    """Live 127.0.0.1 HTTP server speaking the OpenAI-compatible shape the
    real LoopbackHTTPAdapter probes and posts to."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # /v1/models probe
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self):  # /v1/audio/transcriptions
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_real_local_adapter_after_cloud_cost_trip(tmp_path, monkeypatch):
    """A REAL LoopbackHTTPAdapter (live localhost server, actual probe + POST)
    still rescues the run after the cloud budget is spent."""
    from transcription_adapters import LoopbackHTTPAdapter

    server = _loopback_server(
        {"text": "local rescue", "segments": [{"start": 0, "end": 1, "text": "local rescue"}]}
    )
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        request = _many_chunk_request(tmp_path, 1, adapter_order=("groq", "local-http"))
        request.remote_ledger.max_bytes = 0
        request.remote_ledger.max_attempts = 1

        def fake_transcribe_file(backend, key, path, *, max_attempts, language, ledger):
            ledger.charge(50)
            raise SystemExit("HTTP 500")

        monkeypatch.setattr(whisper, "load_api_key", lambda name=None: ("groq", "k"))
        monkeypatch.setattr(whisper, "transcribe_file", fake_transcribe_file)
        local = LoopbackHTTPAdapter(url=url, model="m")
        result = TranscriptionPipeline(
            {"sidecar": _NoSidecar(), "groq": CloudWhisperAdapter("groq"), "local-http": local}
        ).run(request)
    finally:
        server.shutdown()

    assert result.state == "degraded"
    assert result.segments[0].text == "local rescue"
    assert request.remote_ledger.attempts == 1  # local POST never touched the ledger
    assert result.diagnostics["remote_transmission"] is True  # run-level truth
    assert whisper.REMOTE_COST_GUIDANCE not in result.warnings  # complete rescue


def test_both_providers_charge_the_shared_ledger_through_real_sends(tmp_path, monkeypatch):
    """Real whisper.transcribe_file → _post_whisper for BOTH providers, with
    urlopen mocked per endpoint: groq's send fails (charged), openai's
    succeeds (charged) — one shared ledger holds the exact wire total."""
    captured: list[tuple[str, int]] = []
    payload = {"text": "hi", "segments": [{"start": 0, "end": 1, "text": "hi"}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    def routing_urlopen(request, timeout, context):
        captured.append((request.full_url, len(request.data)))
        if "groq" in request.full_url:
            raise _http_error(500)
        return _Resp()

    monkeypatch.setattr(whisper, "urlopen", routing_urlopen)
    monkeypatch.setattr(whisper.time, "sleep", lambda s: None)
    monkeypatch.setattr(whisper, "load_api_key", lambda name=None: (name or "groq", "k"))

    request = _many_chunk_request(
        tmp_path, 1, adapter_order=("groq", "openai"), max_attempts=1
    )
    request.remote_ledger.max_bytes = 10 * 1024 * 1024
    request.remote_ledger.max_attempts = 0
    result = TranscriptionPipeline(
        {
            "sidecar": _NoSidecar(),
            "groq": CloudWhisperAdapter("groq"),
            "openai": CloudWhisperAdapter("openai"),
        }
    ).run(request)

    assert result.state == "degraded"  # openai rescued after groq failed
    endpoints = [url for url, _ in captured]
    assert any("groq" in url for url in endpoints)
    assert any("openai" in url for url in endpoints)
    assert request.remote_ledger.attempts == len(captured)
    assert request.remote_ledger.spent_bytes == sum(n for _, n in captured)


class _NoSidecar:
    requires_audio = False
    is_remote = False
    name = "sidecar"

    def probe(self, request):
        from transcription import AdapterAvailability

        return AdapterAvailability(False, "no_sidecar")

    def transcribe(self, request, receipts):  # pragma: no cover
        raise AssertionError("unavailable adapter must not transcribe")


def test_local_adapters_never_touch_the_ledger(tmp_path):
    request = _many_chunk_request(tmp_path, 1, allow_remote=False)
    media_vtt = request.media_path.with_suffix(".vtt")
    media_vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n", encoding="utf-8"
    )
    from transcription_adapters import SidecarAdapter

    result = SidecarAdapter().transcribe(
        request, ChunkReceiptStore(tmp_path / "off", enabled=False)
    )
    assert result.state == "success"
    assert request.remote_ledger.attempts == 0
    assert request.remote_ledger.spent_bytes == 0


# --- report guidance wiring -----------------------------------------------


@pytest.fixture(scope="module")
def audio_clip(tmp_path_factory):
    """cut_clip is video-only; the transcription path needs an audio stream."""
    import subprocess

    path = tmp_path_factory.mktemp("cost-clips") / "tone.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-t", "2", "-i", "color=c=blue:s=320x240:r=10",
            "-f", "lavfi", "-t", "2", "-i", "sine=frequency=440:sample_rate=16000",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not build audio clip: {result.stderr[:200]}")
    return path


def _cost_limited_attempt():
    from transcription import TranscriptAttempt

    return TranscriptAttempt(
        adapter="groq",
        state="unavailable",
        failure_code="remote_cost_limit_exceeded",
    )


def test_watch_frames_only_run_exits_zero_with_guidance(audio_clip, monkeypatch, capsys):
    import sys as _sys

    import watch
    from transcription import TranscriptResult

    stub = TranscriptResult(
        state="unavailable",
        failure_code="remote_cost_limit_exceeded",
        attempts=(_cost_limited_attempt(),),
        warnings=(whisper.REMOTE_COST_GUIDANCE,),
        diagnostics={"remote_transmission": True},
    )
    monkeypatch.setattr(watch, "transcribe_pipeline", lambda *a, **k: stub)
    monkeypatch.setattr(_sys, "argv", ["watch.py", str(audio_clip), "--detail", "efficient"])
    rc = watch.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Remote cost limit" in out
    assert "--start HH:MM:SS --end HH:MM:SS" in out
    # The transcript-body fallback must not contradict the guidance: keys
    # worked and transcription ran — the budget stopped it, not setup.
    assert "no API key set" not in out
    assert "cost bound" in out


def test_watch_partial_run_exits_zero_with_guidance(audio_clip, monkeypatch, capsys):
    import sys as _sys

    import watch
    from transcription import TranscriptResult, TranscriptSegment

    stub = TranscriptResult(
        state="partial",
        segments=(
            TranscriptSegment(start=0.0, end=1.0, text="opening words", adapter="locallike"),
        ),
        adapter="locallike",
        failure_code="incomplete_chunks",  # run-level code lives in the attempt row
        attempts=(_cost_limited_attempt(),),
        diagnostics={"remote_transmission": True},
    )
    monkeypatch.setattr(watch, "transcribe_pipeline", lambda *a, **k: stub)
    monkeypatch.setattr(_sys, "argv", ["watch.py", str(audio_clip), "--detail", "efficient"])
    rc = watch.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Remote cost limit" in out  # the attempt-row scan branch


def test_watch_complete_rescue_renders_no_guidance(audio_clip, monkeypatch, capsys):
    """Negative control: a cost trip followed by a COMPLETE local rescue has
    nothing left to re-run — the report must not nag with --start/--end."""
    import sys as _sys

    import watch
    from transcription import TranscriptResult, TranscriptSegment

    stub = TranscriptResult(
        state="degraded",
        segments=(
            TranscriptSegment(start=0.0, end=1.0, text="full rescue", adapter="local-http"),
        ),
        adapter="local-http",
        attempts=(_cost_limited_attempt(),),
        diagnostics={"remote_transmission": True},
    )
    monkeypatch.setattr(watch, "transcribe_pipeline", lambda *a, **k: stub)
    monkeypatch.setattr(_sys, "argv", ["watch.py", str(audio_clip), "--detail", "efficient"])
    rc = watch.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "full rescue" in out
    assert "Remote cost limit" not in out


# --- legacy entry point ---------------------------------------------------


def test_legacy_transcribe_video_is_bounded(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    audio = tmp_path / "audio.mp3"

    monkeypatch.setenv("WATCH_REMOTE_MAX_UPLOAD_MB", "1")
    big = b"x" * (2 * 1024 * 1024)

    def fake_extract_audio(video_path, audio_out, *, start_seconds=None, end_seconds=None):
        audio.write_bytes(big)
        return audio

    def must_not_send(request, timeout, context):
        raise AssertionError("HTTP send happened past the cost bound")

    monkeypatch.setattr(whisper, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(whisper, "urlopen", must_not_send)
    with pytest.raises(SystemExit) as excinfo:
        whisper.transcribe_video(str(video), audio, backend="groq", api_key="k")
    assert "--start/--end" in str(excinfo.value)
