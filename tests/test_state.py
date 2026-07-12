from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor

from state import CacheKey, EvidenceState


def key(identity: str = "a", **updates) -> CacheKey:
    values = {
        "source_identity": identity * 64,
        "range_start": 1.0,
        "range_end": 2.0,
        "language": "en",
        "adapter": "sidecar",
        "model": "none",
        "policy": "targeted-v1",
    }
    values.update(updates)
    return CacheKey(**values)


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_atomic_owner_only_store_hit_and_miss(tmp_path):
    root = tmp_path / "state"
    store = EvidenceState(root, ttl_seconds=60, max_bytes=64_000)
    cache_key = key()

    assert store.get(cache_key).status == "miss"
    written = store.put(cache_key, {"stage": "caption", "complete": True}, now=100)
    assert written.stored is True
    assert mode(root) == 0o700
    entries = list(root.glob("*.json"))
    assert len(entries) == 1
    assert mode(entries[0]) == 0o600
    assert not list(root.glob("*.tmp"))
    assert not (root / ".write-lock").exists()

    hit = store.get(cache_key, now=101)
    assert hit.status == "hit"
    assert hit.reason == "verified"
    assert hit.payload == {"stage": "caption", "complete": True}


def test_corruption_checksum_and_unsafe_permissions_are_misses(tmp_path):
    root = tmp_path / "state"
    store = EvidenceState(root)
    cache_key = key()
    assert store.put(cache_key, {"ok": True}).stored
    entry = root / f"{cache_key.digest}.json"

    entry.write_text("not json", encoding="utf-8")
    os.chmod(entry, 0o600)
    assert store.get(cache_key).reason == "corrupt"

    assert store.put(cache_key, {"ok": True}).stored
    envelope = entry.read_text(encoding="utf-8").replace('"ok":true', '"ok":false')
    entry.write_text(envelope, encoding="utf-8")
    os.chmod(entry, 0o600)
    assert store.get(cache_key).reason == "checksum_mismatch"

    os.chmod(entry, 0o644)
    assert store.get(cache_key).reason == "unsafe_permissions"


def test_ttl_and_size_purge_are_bounded(tmp_path):
    root = tmp_path / "state"
    store = EvidenceState(root, ttl_seconds=10, max_bytes=64_000)
    first_key = key("a")
    first = store.put(first_key, {"value": "x" * 500}, now=100)
    assert first.stored
    assert store.get(first_key, now=109).status == "hit"
    assert store.get(first_key, now=110).reason == "expired"
    purged = store.purge(expired_only=True, now=110)
    assert purged.removed_entries == 1
    assert purged.remaining_entries == 0

    first = store.put(first_key, {"value": "x" * 500}, now=200)
    assert first.stored
    store.max_bytes = first.bytes + 64
    second_key = key("b")
    second = store.put(second_key, {"value": "y" * 500}, now=201)
    assert second.stored
    assert store.get(first_key, now=202).status == "miss"
    assert store.get(second_key, now=202).status == "hit"
    status = store.verify(now=202)
    assert status["bytes"] <= store.max_bytes

    removed = store.purge()
    assert removed.removed_entries == 1
    assert removed.remaining_bytes == 0


def test_concurrent_duplicate_writes_leave_one_verified_entry(tmp_path):
    root = tmp_path / "state"
    store = EvidenceState(root, max_bytes=128_000)
    cache_key = key()

    def write(index: int):
        return store.put(cache_key, {"writer": index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(16)))

    assert all(result.stored for result in results)
    hit = store.get(cache_key)
    assert hit.status == "hit"
    assert hit.payload["writer"] in range(16)
    assert len(list(root.glob("*.json"))) == 1
    assert not list(root.glob("*.tmp"))
    assert not (root / ".write-lock").exists()


def test_sensitive_media_secret_and_private_path_persistence_are_refused(tmp_path):
    cache_key = key()
    store = EvidenceState(tmp_path / "state")
    assert store.put(cache_key, {"text": "private words"}, payload_kind="transcript").reason == (
        "sensitive_persistence_not_enabled"
    )
    assert store.put(cache_key, {"bytes": "..."}, payload_kind="video").reason == (
        "media_persistence_forbidden"
    )
    assert not store.put(cache_key, {"authorization": "Bearer secret"}).stored
    assert not store.put(cache_key, {"manifest": "/Users/private/video.mp4"}).stored
    assert not store.put(cache_key, {"frame": "frames/one.jpg"}).stored

    opted_in = EvidenceState(tmp_path / "sensitive", allow_sensitive=True)
    assert opted_in.put(cache_key, {"text": "private words"}, payload_kind="transcript").stored
    assert not store.put(cache_key, {"segments": []}, payload_kind="scout").stored
    assert opted_in.put(cache_key, {"segments": []}, payload_kind="scout").stored
