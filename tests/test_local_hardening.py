"""Hardening carried over from the local fork's adversarial audit (2026-07-13).

Each of these was verified as a real defect in this repo before being fixed:

- yap rejects a bare locale ("Locale \"en\" is not supported") AND exits 0 while
  doing so, so WATCH_LANGUAGE=en silently fed yap's error text to the parser.
- The loopback adapter used urlopen, which follows 3xx. A hostile machine-local
  STT server could 302 the audio to an external host, defeating the skill's
  central "audio never leaves your machine" guarantee.
- The receipt store rewrote and fsynced the entire JSON file on every chunk, and
  sorted its keys, which made eviction hash-ordered rather than FIFO.
- Chunks were capped at 24MB -- the cloud *upload* limit, not a transcription
  bound -- handing a CPU-bound local model ~50 minutes of audio per request.
"""
from __future__ import annotations

import json

import pytest

import transcription_adapters as ta
import transcription_chunks as tc


# --- yap locale normalization -------------------------------------------------

@pytest.mark.parametrize(
    "given,expected",
    [
        ("en", "en_US"),      # the natural value; yap rejects it outright
        ("fr", "fr_FR"),
        ("ja", "ja_JP"),
        ("en-GB", "en_GB"),   # already regioned, just normalized
        ("en_us", "en_US"),
        ("pt", "pt_BR"),
    ],
)
def test_yap_locale_is_normalized(given, expected):
    assert ta._yap_locale(given) == expected


def test_unknown_language_passes_through_untouched():
    """Don't invent a region for a language we have no mapping for."""
    assert ta._yap_locale("xx") == "xx"


# --- loopback SSRF ------------------------------------------------------------

def test_loopback_opener_refuses_redirects():
    """A 3xx from the local STT server must raise, never be followed."""
    handler = ta._NoRedirects()
    with pytest.raises(Exception) as exc:
        handler.redirect_request(
            None, None, 302, "Found", {}, "https://evil.example.com/collect"
        )
    assert "refusing" in str(exc.value).lower()
    assert "evil.example.com" in str(exc.value)


def test_loopback_opener_is_actually_wired_in():
    """Guard against a future edit reverting to a redirect-following urlopen."""
    source = (ta.__file__)
    text = open(source, encoding="utf-8").read()
    assert "_LOOPBACK_OPENER.open(" in text
    assert "urlopen(" not in text, "urlopen follows redirects; use _LOOPBACK_OPENER"


# --- chunk sizing -------------------------------------------------------------

def test_chunk_cap_is_sized_for_a_local_model_not_a_cloud_upload_limit():
    # 64kbps mono => ~480KB/min. The old 24MB cap was ~50 minutes in one request.
    assert tc.DEFAULT_MAX_CHUNK_BYTES < 4 * 1024 * 1024
    minutes = tc.DEFAULT_MAX_CHUNK_BYTES / (64_000 / 8 * 60)
    assert 1.0 <= minutes <= 6.0, f"chunk is {minutes:.1f} min of audio"


# --- receipt store: batching, FIFO, and failure tolerance ---------------------

def _chunk(idx: int) -> tc.AudioChunk:
    return tc.AudioChunk(
        index=idx, path=None, sha256=f"{idx:064x}", source_offset=float(idx), duration=1.0
    )


def test_receipts_are_batched_not_written_every_put(tmp_path, monkeypatch):
    store = tc.ChunkReceiptStore(tmp_path / "r.json")
    writes = []
    real_write = store._write
    monkeypatch.setattr(store, "_write", lambda: (writes.append(1), real_write())[1])

    for i in range(tc.RECEIPT_FLUSH_EVERY - 1):
        store.put("yap", "m", "en", _chunk(i), [{"start": 0, "end": 1, "text": "x"}])
    assert writes == [], "must not rewrite the whole file on every chunk"

    store.put("yap", "m", "en", _chunk(99), [{"start": 0, "end": 1, "text": "x"}])
    assert len(writes) == 1, "should flush once the batch fills"


def test_final_flush_persists_the_tail(tmp_path):
    store = tc.ChunkReceiptStore(tmp_path / "r.json")
    store.put("yap", "m", "en", _chunk(0), [{"start": 0, "end": 1, "text": "x"}])
    assert not (tmp_path / "r.json").exists()  # still buffered
    store.flush()
    data = json.loads((tmp_path / "r.json").read_text())
    assert len(data["entries"]) == 1


def test_flush_is_idempotent(tmp_path):
    store = tc.ChunkReceiptStore(tmp_path / "r.json")
    store.flush()  # nothing pending
    store.put("yap", "m", "en", _chunk(0), [{"start": 0, "end": 1, "text": "x"}])
    store.flush()
    store.flush()
    assert json.loads((tmp_path / "r.json").read_text())["entries"]


def test_eviction_is_fifo_not_hash_ordered(tmp_path):
    """sort_keys=True made a reloaded store evict by key hash, dropping arbitrary
    receipts instead of the oldest."""
    store = tc.ChunkReceiptStore(tmp_path / "r.json")
    for i in range(tc.MAX_RECEIPT_ENTRIES + 10):
        store.put("yap", "m", "en", _chunk(i), [{"start": 0, "end": 1, "text": str(i)}])
    store.flush()

    reloaded = tc.ChunkReceiptStore(tmp_path / "r.json")
    entries = reloaded._data["entries"]
    assert len(entries) == tc.MAX_RECEIPT_ENTRIES
    # The 10 oldest must be the ones gone: the newest chunk must still be there.
    newest = tc.ChunkReceiptStore._key("yap", "m", "en", _chunk(tc.MAX_RECEIPT_ENTRIES + 9))
    assert newest in entries
    oldest = tc.ChunkReceiptStore._key("yap", "m", "en", _chunk(0))
    assert oldest not in entries


def test_written_order_is_insertion_order(tmp_path):
    """FIFO eviction depends on insertion order surviving a reload. Assert that
    directly -- asserting merely "not sorted" would pass by luck 1 run in 6."""
    store = tc.ChunkReceiptStore(tmp_path / "r.json")
    inserted = []
    for i in range(6):
        store.put("yap", "m", "en", _chunk(i), [{"start": 0, "end": 1, "text": str(i)}])
        inserted.append(tc.ChunkReceiptStore._key("yap", "m", "en", _chunk(i)))
    store.flush()
    written = list(json.loads((tmp_path / "r.json").read_text())["entries"])
    assert written == inserted
