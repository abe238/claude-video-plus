"""R2a-1: chunk-level no_speech terminal state (L4; binding amendments in
docs/LOOP_CHAIN_2026-07-18.md).

The pipeline-order bug this fixes: adapters run local-http → yap → whisper-cli →
cloud, so a silent clip used to reach the FIRST adapter and hallucinate, and a
zero-segment result read as "unavailable" causing fall-through — potentially
uploading silence to the cloud. Silence is classified at the shared chunk layer
(ffmpeg silencedetect, already run for chunk placement) BEFORE any adapter.

Binding semantics:
- whole-transcript no_speech ONLY when ALL chunks are silent;
- a silent chunk in a mixed file is skipped (not failed) and never suppresses
  speech elsewhere;
- classifier failure ⇒ treat as speech (never gate on a broken instrument);
- no_speech is terminal: usable() is False but NO adapter fall-through occurs
  and nothing is uploaded;
- no_speech is never cached in receipts (recomputed each run, so a threshold
  change can never serve a stale classification — satisfies the
  classifier-version amendment by construction).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import transcription
import transcription_chunks as tc


def _make_audio(path: Path, *parts: str) -> Path:
    """Concat lavfi segments, e.g. anullsrc (silence) and sine (speech-class)."""
    inputs, filters = [], []
    for i, part in enumerate(parts):
        inputs += ["-f", "lavfi", "-t", "4", "-i", part]
        filters.append(f"[{i}:a]")
    filter_complex = "".join(filters) + f"concat=n={len(parts)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", filter_complex, "-map", "[out]",
         "-ac", "1", "-ar", "16000", "-y", str(path)],
        check=True, capture_output=True,
    )
    return path


@pytest.fixture()
def silent_wav(tmp_path):
    return _make_audio(tmp_path / "silent.wav", "anullsrc=r=16000:cl=mono")


@pytest.fixture()
def mixed_wav(tmp_path):
    # 4s silence + 4s tone: the tone is "non-silent" to the classifier
    # (speech-class at this tier; Silero refines music/noise later in R2a-2).
    return _make_audio(tmp_path / "mixed.wav", "anullsrc=r=16000:cl=mono", "sine=frequency=440")


@pytest.fixture()
def tone_wav(tmp_path):
    return _make_audio(tmp_path / "tone.wav", "sine=frequency=440")


# --- state contract -------------------------------------------------------------

def test_no_speech_is_a_transcript_state():
    assert "no_speech" in transcription.TRANSCRIPT_STATES


def test_no_speech_truth_table():
    r = transcription.TranscriptResult(state="no_speech", language="auto")
    assert r.usable is False          # no content to read
    assert r.state != "fatal"           # not an error
    # terminal: the pipeline must never fall through past it (behavior test below)


def test_fatal_still_requires_failure_code():
    with pytest.raises(Exception):
        transcription.TranscriptResult(state="fatal", language="auto")


# --- classifier -----------------------------------------------------------------

def test_all_silent_audio_classifies_no_speech(silent_wav, tmp_path):
    prepared = tc.prepare_audio(silent_wav, tmp_path / "work")
    assert prepared.all_silent is True
    assert all(c.silent for c in prepared.chunks)


def test_mixed_audio_marks_only_silent_chunks(mixed_wav, tmp_path):
    # force one chunk per half (8s @64kbps ≈ 64KB total)
    prepared = tc.prepare_audio(mixed_wav, tmp_path / "work", max_chunk_bytes=32 * 1024)
    assert prepared.all_silent is False
    flags = [c.silent for c in prepared.chunks]
    assert any(flags) and not all(flags)


def test_quiet_but_nonsilent_audio_is_speech(tone_wav, tmp_path):
    """False-negative guard: anything above the silence threshold is
    speech-class at this tier — quiet speech must never be gated away."""
    prepared = tc.prepare_audio(tone_wav, tmp_path / "work")
    assert prepared.all_silent is False
    assert not any(c.silent for c in prepared.chunks)


def test_classifier_failure_treats_as_speech(silent_wav, tmp_path, monkeypatch):
    """A broken instrument must never gate: if silencedetect fails, every
    chunk is speech-class and the pipeline proceeds normally."""
    real_run = subprocess.run
    def broken(cmd, **kwargs):
        if any("silencedetect" in str(c) for c in cmd):
            raise subprocess.TimeoutExpired(cmd, 1)
        return real_run(cmd, **kwargs)
    monkeypatch.setattr(tc.subprocess, "run", broken)
    prepared = tc.prepare_audio(silent_wav, tmp_path / "work")
    assert prepared.all_silent is False
    assert not any(c.silent for c in prepared.chunks)


# --- pipeline: terminal, no fall-through, no upload ------------------------------

class _NoSidecar:
    """The pipeline always consults sidecar first; this stub reports absent."""
    name = "sidecar"
    requires_audio = False
    is_remote = False
    def probe(self, request):
        return transcription.AdapterAvailability(False, "sidecar_not_found")
    def transcribe(self, request, receipts):
        raise AssertionError("sidecar stub must never transcribe")


class _SpyAdapter:
    name = "spy"
    requires_audio = True
    is_remote = False
    def __init__(self):
        self.probed = 0
        self.transcribed = 0
    def probe(self, request):
        self.probed += 1
        return transcription.AdapterAvailability(True)
    def transcribe(self, request, receipts):
        self.transcribed += 1
        return transcription.TranscriptResult(
            state="success", language=request.language, adapter=self.name,
            segments=(transcription.TranscriptSegment.from_mapping(
                {"start": 0.0, "end": 1.0, "text": "hallucinated"},
                language=request.language, adapter=self.name, model=None), ),
        )


def test_all_silent_short_circuits_before_any_adapter(silent_wav, tmp_path):
    spy = _SpyAdapter()
    pipeline = transcription.TranscriptionPipeline({"sidecar": _NoSidecar(), "spy": spy})
    request = transcription.TranscriptionRequest(
        media_path=silent_wav, work_dir=tmp_path / "w", language="auto",
        adapter_order=("spy",),
    )
    result = pipeline.run(request)
    assert result.state == "no_speech"
    # L6 review relaxation: probes are local and upload nothing, so lazy
    # prepare-after-probe restores the zero-work path on backend-less machines.
    # The binding guarantee is enforced where upload happens: transcribe.
    assert spy.transcribed == 0  # nothing transcribed, nothing uploaded


class _ChunkedSpyAdapter(_SpyAdapter):
    """Routes through the REAL _run_chunked so the silent-skip logic is what
    gets tested, not a fake."""
    def transcribe(self, request, receipts):
        import transcription_adapters as ta
        self.transcribed += 1
        return ta._run_chunked(
            request, receipts, adapter=self.name, model=None,
            transcribe_one=lambda chunk: [{"start": 0.0, "end": 1.0, "text": "ok"}],
            remote=False,
        )


def test_mixed_audio_transcribes_speech_and_skips_silent(mixed_wav, tmp_path):
    """A silent chunk never suppresses speech elsewhere, and is not a failure."""
    prepared = tc.prepare_audio(mixed_wav, tmp_path / "prep", max_chunk_bytes=32 * 1024)
    assert any(c.silent for c in prepared.chunks) and not prepared.all_silent
    spy = _ChunkedSpyAdapter()
    pipeline = transcription.TranscriptionPipeline({"sidecar": _NoSidecar(), "spy": spy})
    request = transcription.TranscriptionRequest(
        media_path=mixed_wav, work_dir=tmp_path / "w", language="auto",
        adapter_order=("spy",), prepared_audio=prepared,
    )
    result = pipeline.run(request)
    # "degraded" is the pipeline's pre-existing honesty signal for earlier
    # UNAVAILABLE adapters (the absent sidecar here) — silence must not make it
    # "partial" (partial = incomplete chunks = failure-class).
    assert result.state in {"success", "degraded"}
    assert result.state != "partial"           # silence is not failure
    assert result.segments                     # speech chunk transcribed
    assert result.diagnostics.get("silent_chunks", 0) >= 1


# --- report label ----------------------------------------------------------------

def test_status_label_distinguishes_no_speech_from_unavailable():
    silent = transcription.TranscriptResult(state="no_speech", language="auto")
    gone = transcription.TranscriptResult(state="unavailable", language="auto")
    assert "no speech" in transcription.transcript_status_label(silent).lower()
    assert transcription.transcript_status_label(gone) is None  # existing message path
