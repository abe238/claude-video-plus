"""P2: opt-in content-addressed video cache (idea from m1crodevil/hermes-video,
rebuilt per the Codex-hardened constraint set in the deep-pass plan).

The binding claims: byte-identity PROVEN on every hit, exclusions are
outright (no consent path), every cache failure is a plain miss, and
EvidenceState's media refusal is never touched (this store is separate).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

import video_cache
from video_cache import VideoCache, cache_enabled, cache_identity


# --- identity / exclusion policy -------------------------------------------


def test_youtube_url_forms_share_one_identity():
    a = cache_identity("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    b = cache_identity("https://youtu.be/dQw4w9WgXcQ")
    c = cache_identity("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123")
    d = cache_identity("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
    assert a and a == b == c == d


def test_audio_only_is_a_separate_entry():
    video = cache_identity("https://youtu.be/dQw4w9WgXcQ")
    audio = cache_identity("https://youtu.be/dQw4w9WgXcQ", audio_only=True)
    assert video and audio and video != audio


def test_cookie_configured_refuses_caching_outright():
    assert cache_identity("https://youtu.be/dQw4w9WgXcQ", cookie_spec="chrome") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.com/video.mp4",           # credentials
        "https://cdn.example.com/v.mp4?X-Amz-Signature=abc",  # signed
        "https://cdn.example.com/v.mp4?token=xyz",            # token-bearing
        "https://example.com/v.mp4?anything=1",               # ANY query, unknown host
        "https://example.com/v.mp4#fragment",
        "http://example.com/video.mp4",                       # HTTPS only
        "http://youtu.be/dQw4w9WgXcQ",                         # HTTPS only, even YouTube
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&token=s3cret",   # auth-bearing param
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&signature=abc",  # signature param
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ#t=1",     # fragment
        "ftp://example.com/v.mp4",                            # non-http(s)
        "https://www.youtube.com/watch",                      # no video id
        "https://www.youtube.com/watch?v=bad id!",            # malformed id
    ],
)
def test_uncacheable_sources_are_refused(url):
    assert cache_identity(url) is None


def test_generic_hosts_are_out_of_scope_for_now():
    # v1.5.5 caches the known-public YouTube host set only: a generic FQDN
    # can be mapped to private space by DNS or /etc/hosts, so lexical checks
    # cannot prove it public. Widening requires address-resolution packets.
    assert cache_identity("https://example.com/talks/keynote.mp4") is None
    assert cache_identity("https://home.arpa/v.mp4") is None
    assert cache_identity("https://home.arpa./v.mp4") is None


def test_cache_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WATCH_VIDEO_CACHE", raising=False)
    assert cache_enabled() is False
    assert cache_enabled({"WATCH_VIDEO_CACHE": "1"}) is True
    monkeypatch.setenv("WATCH_VIDEO_CACHE", "true")
    assert cache_enabled() is True


# --- store behavior ---------------------------------------------------------


def _cache(tmp_path: Path, **kw) -> VideoCache:
    return VideoCache(tmp_path / "vc", **kw)


def _media(tmp_path: Path, name="clip.mp4", size=4096) -> Path:
    path = tmp_path / name
    path.write_bytes(os.urandom(size))
    path.chmod(0o644)  # what yt-dlp actually writes under a normal umask —
    # the live positive control caught insert() refusing exactly this
    return path


IDENTITY = "a" * 64


def test_hit_bytes_are_proven_identical(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    original = media.read_bytes()
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    served = cache.lookup(IDENTITY, tmp_path / "work")
    assert served is not None
    assert served.read_bytes() == original  # byte-for-byte, not just hash
    assert served.parent == tmp_path / "work"  # a COPY in the work dir


def test_corrupted_object_is_evicted_on_hit(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.chmod(0o600)
    with obj.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"CORRUPT")
    assert cache.lookup(IDENTITY, tmp_path / "work") is None  # per-hit checksum
    assert cache.lookup(IDENTITY, tmp_path / "work2") is None  # evicted
    assert not list((cache.root / "objects").glob("*.mp4"))


def test_symlinked_object_is_refused(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    [obj] = (cache.root / "objects").glob("*.mp4")
    target = tmp_path / "elsewhere.mp4"
    shutil.move(obj, target)
    os.symlink(target, obj)
    assert cache.lookup(IDENTITY, tmp_path / "work") is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_world_readable_object_is_refused(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.chmod(0o644)
    assert cache.lookup(IDENTITY, tmp_path / "work") is None


def test_ttl_expiry_evicts(tmp_path):
    cache = _cache(tmp_path, ttl_seconds=1)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"][IDENTITY]["stored_at"] = time.time() - 3600
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    assert cache.lookup(IDENTITY, tmp_path / "work") is None


def test_lru_bound_evicts_least_recently_used(tmp_path):
    cache = _cache(tmp_path, max_total_bytes=10_000)
    old = _media(tmp_path, "old.mp4", 4096)
    new = _media(tmp_path, "new.mp4", 4096)
    third = _media(tmp_path, "third.mp4", 4096)
    assert cache.insert("1" * 64, old, source_url="https://example.com/1.mp4")
    time.sleep(0.02)
    assert cache.insert("2" * 64, new, source_url="https://example.com/2.mp4")
    # Touch entry 1 so entry 2 becomes the LRU victim.
    assert cache.lookup("1" * 64, tmp_path / "w1") is not None
    assert cache.insert("3" * 64, third, source_url="https://example.com/3.mp4")
    assert cache.lookup("2" * 64, tmp_path / "w2") is None   # evicted
    assert cache.lookup("1" * 64, tmp_path / "w3") is not None
    assert cache.lookup("3" * 64, tmp_path / "w4") is not None


def test_oversized_entry_bypasses_without_error(tmp_path):
    cache = _cache(tmp_path, max_entry_bytes=100)
    media = _media(tmp_path, size=4096)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is False
    assert cache.lookup(IDENTITY, tmp_path / "work") is None


def test_disk_headroom_guard_skips_insert(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    usage = shutil.disk_usage(str(tmp_path))
    monkeypatch.setattr(
        video_cache.shutil, "disk_usage",
        lambda _p: type(usage)(usage.total, usage.used, video_cache.DISK_HEADROOM_BYTES - 1),
    )
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is False


def test_same_content_under_two_identities_stores_one_object(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    other = tmp_path / "same-bytes.mp4"
    shutil.copyfile(media, other)
    other.chmod(0o644)
    assert cache.insert("1" * 64, media, source_url="https://example.com/a.mp4")
    assert cache.insert("2" * 64, other, source_url="https://example.com/b.mp4")
    assert len(list((cache.root / "objects").glob("*.mp4"))) == 1  # content-addressed
    assert cache.lookup("1" * 64, tmp_path / "w1") is not None
    assert cache.lookup("2" * 64, tmp_path / "w2") is not None


def test_any_cache_failure_is_a_plain_miss_with_notice(tmp_path, monkeypatch, capsys):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")

    def exploding_read_index(self):
        raise OSError("index io")

    monkeypatch.setattr(VideoCache, "_read_index", exploding_read_index)
    assert cache.lookup(IDENTITY, tmp_path / "work") is None  # fail-open
    assert "video cache lookup failed (OSError)" in capsys.readouterr().err


def test_windows_profile_root_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(video_cache, "_IS_WINDOWS", True)
    outside = Path("/srv/video-cache") if os.name != "nt" else Path("C:/srv/video-cache")
    cache = VideoCache(outside)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is False
    assert cache.lookup(IDENTITY, tmp_path / "work") is None


def test_purge_and_inspect(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    report = cache.inspect()
    assert report["entry_count"] == 1
    assert report["total_bytes"] == 4096
    assert report["entries"][0]["source_url"] == "https://example.com/v.mp4"
    assert cache.purge() is True
    # Root + lock survive by design (a purge racing a writer must serialize);
    # contents are gone.
    assert cache.root.exists()
    assert not (cache.root / "index.json").exists()
    assert cache.inspect()["entry_count"] == 0


def test_index_sanitizes_urls_inside_insert(tmp_path):
    # The STORE enforces the secret-free index, whatever the caller passes:
    # query strings are dropped (a validated YouTube id survives), userinfo
    # refuses the insert entirely.
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(
        IDENTITY, media,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&token=s3cret&sig=xyz",
    )
    raw = (cache.root / "index.json").read_text()
    # CONTRACTS.md: NO query data of any kind reaches the index — not the
    # secret params, and not even a reconstructed video id.
    assert "s3cret" not in raw and "sig=" not in raw and "token" not in raw
    assert "?" not in json.loads(raw)["entries"][IDENTITY]["source_url"]
    media2 = _media(tmp_path, "second.mp4")
    assert cache.insert("b" * 64, media2, source_url="https://user:pw@example.com/v.mp4") is False
    assert "user:pw" not in (cache.root / "index.json").read_text()


# --- end-to-end through watch.main ------------------------------------------


def _wire_fake_download(monkeypatch, watch, clip: Path, counter: dict):
    def fake_fetch_captions(source, out_dir):
        return {"subtitle_path": None, "info": {"title": "t", "duration": 5, "availability": "public"},
                "downloaded": False, "cookie_used": False,
                "selected_strategy": "default", "attempts": []}

    def fake_download(source, out_dir, **kwargs):
        counter["downloads"] += 1
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        served = out_dir / "video.mp4"
        shutil.copyfile(clip, served)
        served.chmod(0o644)
        return {"subtitle_path": None, "info": {"title": "t", "duration": 5, "availability": "public"},
                "video_path": str(served), "downloaded": True, "cookie_used": False,
                "selected_strategy": "default", "attempts": []}

    monkeypatch.setattr(watch, "fetch_captions", fake_fetch_captions)
    monkeypatch.setattr(watch, "download", fake_download)


def test_end_to_end_cold_then_hit(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys
    import time as _time

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)
    url = "https://www.youtube.com/watch?v=cachetest01"
    argv = ["watch.py", url, "--no-whisper", "--detail", "efficient"]

    monkeypatch.setattr(_sys, "argv", list(argv))
    t0 = _time.perf_counter()
    assert watch.main() == 0
    cold_seconds = _time.perf_counter() - t0
    cold_out = capsys.readouterr().out
    assert counter["downloads"] == 1

    monkeypatch.setattr(_sys, "argv", list(argv))
    t0 = _time.perf_counter()
    assert watch.main() == 0
    hit_seconds = _time.perf_counter() - t0
    captured = capsys.readouterr()
    hit_out = captured.out
    assert counter["downloads"] == 1  # ZERO new downloads on the hit
    assert "serving media from the local video cache (verified, experimental)" in captured.err

    # Output equivalence: the FULL normalized reports must match (work-dir
    # paths and the run-specific frame stamps are the only run-varying text).
    import re as _re

    def _normalize(text):
        text = _re.sub(r"(?:[A-Za-z]:)?[\\/][^\s`]*watch-[^\s`]*", "<WORK>", text)
        text = _re.sub(r"/private/[^\s`]+", "<WORK>", text)
        text = _re.sub(r"(?:[A-Za-z]:)?[\\/][^\s`]*[Tt]emp[\\/][^\s`]+", "<WORK>", text)
        # The experimental participation marker is the DECLARED per-run
        # difference (CONTRACTS.md incomplete-feature gate): cold says miss,
        # hit says hit — strip the whole line either way.
        text = _re.sub(r"- \*\*Video cache \(experimental\):\*\* [^\n]*\n", "", text)
        # The hit's Acquisition line is also DECLARED: it names the cache as
        # the media source while keeping the caption probe separate.
        text = text.replace("media from local video cache; caption probe ", "")
        return text

    assert _normalize(cold_out) == _normalize(hit_out)
    # Frame hashes byte-identical across cold and hit runs.
    import hashlib as _hashlib

    def _frame_hashes(out_text):
        paths = _re.findall(r"`([^`]*frames[\\/]frame_[^`]+\.jpg)`", out_text)
        return [_hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]

    cold_hashes = _frame_hashes(cold_out)
    assert cold_hashes and cold_hashes == _frame_hashes(hit_out)
    print(f"[measurement] cold={cold_seconds:.3f}s hit={hit_seconds:.3f}s")


def test_hit_skips_consent_miss_still_gated(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setenv("WATCH_DOWNLOAD_CONSENT", "required")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)

    # Miss: uncaptioned URL + consent required → exit 5, nothing downloaded.
    monkeypatch.setattr(_sys, "argv", ["watch.py", "https://youtu.be/consenttest1", "--no-whisper"])
    assert watch.main() == 5
    assert counter["downloads"] == 0
    capsys.readouterr()

    # Seed the cache via an allowed run.
    monkeypatch.setattr(
        _sys, "argv",
        ["watch.py", "https://youtu.be/consenttest1", "--no-whisper", "--allow-download"],
    )
    assert watch.main() == 0
    assert counter["downloads"] == 1
    capsys.readouterr()

    # Hit: consent gate does not fire — nothing is downloaded, and the
    # banner names the cache (asserted from stderr, where it prints).
    monkeypatch.setattr(_sys, "argv", ["watch.py", "https://youtu.be/consenttest1", "--no-whisper"])
    assert watch.main() == 0
    captured = capsys.readouterr()
    assert counter["downloads"] == 1
    assert "serving media from the local video cache (verified, experimental)" in captured.err


def test_cache_off_by_default_never_stores(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys

    import watch

    monkeypatch.delenv("WATCH_VIDEO_CACHE", raising=False)
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)
    monkeypatch.setattr(
        _sys, "argv",
        ["watch.py", "https://youtu.be/defaultoff01", "--no-whisper", "--detail", "efficient"],
    )
    assert watch.main() == 0
    capsys.readouterr()
    assert counter["downloads"] == 1
    assert not (tmp_path / "vc").exists()  # nothing persisted without opt-in


# --- adversarial regressions (round-1 gate findings) ------------------------


def _poison_index(cache: VideoCache, identity: str, digest: str, suffix: str):
    cache._prepare()
    index = {"schema_version": 1, "entries": {identity: {
        "digest": digest, "suffix": suffix, "size": 1,
        "stored_at": time.time(), "last_used": time.time()}}}
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)


def test_poisoned_index_cannot_unlink_outside_the_cache(tmp_path):
    sentinel = tmp_path / "outside-victim"
    sentinel.write_text("precious")
    cache = _cache(tmp_path)
    # Absolute-path digest and traversal digest: both must be inert.
    for digest in (str(sentinel), f"../../{sentinel.name}"):
        _poison_index(cache, IDENTITY, digest, ".mp4")
        assert cache.lookup(IDENTITY, tmp_path / "work") is None
        assert sentinel.exists() and sentinel.read_text() == "precious"
    # Poisoned suffix as well.
    _poison_index(cache, IDENTITY, "a" * 64, f"/../{sentinel.name}")
    assert cache.lookup(IDENTITY, tmp_path / "work") is None
    assert sentinel.exists()


def test_dedupe_survives_eviction_of_one_identity(tmp_path):
    cache = _cache(tmp_path, ttl_seconds=10_000)
    media = _media(tmp_path)
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("1" * 64, media, source_url="https://example.com/a.mp4")
    assert cache.insert("2" * 64, other, source_url="https://example.com/b.mp4")
    # Expire ONLY identity 1 via a targeted index edit.
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"]["1" * 64]["stored_at"] = time.time() - 1_000_000
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    # Identity 1 is gone; identity 2 still serves the SHARED object.
    assert cache.lookup("1" * 64, tmp_path / "w1") is None
    assert cache.lookup("2" * 64, tmp_path / "w2") is not None
    assert len(list((cache.root / "objects").glob("*.mp4"))) == 1


def test_unique_object_accounting_under_lru(tmp_path):
    # Two identities sharing one 4 KiB object must count 4 KiB, not 8 KiB:
    # with a 6 KiB bound nothing may be evicted.
    cache = _cache(tmp_path, max_total_bytes=6 * 1024)
    media = _media(tmp_path)
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("1" * 64, media, source_url="https://example.com/a.mp4")
    assert cache.insert("2" * 64, other, source_url="https://example.com/b.mp4")
    assert cache.lookup("1" * 64, tmp_path / "w1") is not None
    assert cache.lookup("2" * 64, tmp_path / "w2") is not None


def test_interrupted_insert_leaves_no_incoming_file(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    real_read = os.read

    def failing_read(fd, n):
        raise OSError("mid-copy failure")

    monkeypatch.setattr(os, "read", failing_read)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is False
    monkeypatch.setattr(os, "read", real_read)
    leftovers = list((cache.root / "objects").glob(".incoming.*"))
    assert leftovers == []  # the finally cleaned up


def test_stale_incoming_files_are_swept(tmp_path):
    cache = _cache(tmp_path)
    cache._prepare()
    stale = cache.root / "objects" / ".incoming.999.deadbeef.tmp"
    stale.write_bytes(b"crashed writer")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    assert not stale.exists()


def test_live_lock_blocks_second_writer_without_theft(tmp_path, monkeypatch):
    """Two contenders on the OS-backed advisory lock: while one HOLDS it, the
    other times out — the kernel serializes, nothing is stolen, and a dead
    holder's lock releases automatically (fd close) with no staleness code.
    Runs the flock branch on POSIX and the msvcrt branch on Windows."""
    monkeypatch.setattr(video_cache, "LOCK_WAIT_SECONDS", 0.1)
    cache = _cache(tmp_path)
    cache._prepare()
    holder_fd = os.open(cache.root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(holder_fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(holder_fd, fcntl.LOCK_EX)
    media = _media(tmp_path)
    try:
        assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is False
    finally:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(holder_fd, msvcrt.LK_UNLCK, 1)
        os.close(holder_fd)  # releases the lock, like a holder's death would
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4") is True


def test_poisoned_scalar_entries_read_as_absent(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"][IDENTITY]["size"] = []          # poisoned scalar
    index["entries"]["b" * 64] = {"digest": "a" * 64, "suffix": ".mp4",
                                  "size": 1, "stored_at": {}, "last_used": None}
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    # No TypeError anywhere: both entries read as absent (fail-open).
    assert cache.lookup(IDENTITY, tmp_path / "w1") is None
    assert cache.lookup("b" * 64, tmp_path / "w2") is None
    assert cache.inspect()["entry_count"] == 0


def test_nonfinite_bounds_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("WATCH_VIDEO_CACHE_MAX_GB", "inf")
    monkeypatch.setenv("WATCH_VIDEO_CACHE_TTL_DAYS", "nan")
    cache = VideoCache(Path("/tmp/unused-root"))
    assert cache.max_total_bytes == video_cache.DEFAULT_MAX_TOTAL_BYTES
    assert cache.ttl_seconds == video_cache.DEFAULT_TTL_SECONDS


def test_watch_helpers_survive_unexpected_cache_errors(tmp_path, monkeypatch, capsys):
    import watch

    def exploding(self, *a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(video_cache.VideoCache, "lookup", exploding)
    monkeypatch.setattr(video_cache.VideoCache, "insert", exploding)
    ok_probe = {"info": {"availability": "public"}, "cookie_used": False}
    assert watch._cache_lookup_media("a" * 64, tmp_path / "w", ok_probe) is None
    err = capsys.readouterr().err
    assert "video cache lookup failed (RuntimeError)" in err

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    clip = _media(tmp_path)

    def fake_download(source, out_dir, **kwargs):
        return {"video_path": str(clip), "cookie_used": False,
                "info": {"availability": "public"}}

    monkeypatch.setattr(watch, "download", fake_download)
    result = watch._download_and_cache(
        "https://youtu.be/errtest00001", tmp_path / "dl",
        key=video_cache.cache_identity("https://youtu.be/errtest00001"),
    )
    assert result["video_path"] == str(clip)  # the run continues fresh
    assert "video cache store failed (RuntimeError)" in capsys.readouterr().err


def test_insert_revalidates_exclusion_at_store_time(tmp_path, monkeypatch, capsys):
    """Cookies configured between key computation and insert: the media was
    fetched with authorization and must NOT be retained."""
    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    clip = _media(tmp_path)
    key = video_cache.cache_identity("https://youtu.be/revalidate01")

    def cookie_appearing_download(source, out_dir, **kwargs):
        monkeypatch.setenv("WATCH_COOKIES_BROWSER", "chrome")  # config mutates mid-run
        return {"video_path": str(clip), "cookie_used": False,
                "info": {"availability": "public"}}

    monkeypatch.setattr(watch, "download", cookie_appearing_download)
    watch._download_and_cache("https://youtu.be/revalidate01", tmp_path / "dl", key=key)
    monkeypatch.delenv("WATCH_COOKIES_BROWSER")
    assert VideoCache(tmp_path / "vc").lookup(key, tmp_path / "w") is None  # never stored


# --- round-3 regressions ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/v.mp4",
        "https://127.0.0.1/v.mp4",
        "https://10.0.0.1/v.mp4",
        "https://192.168.1.5/clip.mp4",
        "https://[fe80::1]/v.mp4",
        "https://intranet/v.mp4",           # dotless single-label host
        "https://nas.local/v.mp4",
        "https://media.internal/v.mp4",
    ],
)
def test_private_network_sources_are_refused(url):
    assert cache_identity(url) is None


def test_cookie_used_acquisition_is_never_inserted_aba(tmp_path, monkeypatch):
    """ABA race: no cookie at key time → cookie configured during download →
    cookie removed before insert. The acquisition's own cookie_used fact
    forbids retention regardless of insert-time config."""
    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    clip = _media(tmp_path)
    key = video_cache.cache_identity("https://youtu.be/abaRace00001")
    assert key

    def cookie_download(source, out_dir, **kwargs):
        # By download time cookies were configured AND removed again — the
        # returned fact is what the acquisition actually did. availability is
        # public so the cookie fact is the ONLY thing blocking retention.
        return {"video_path": str(clip), "cookie_used": True,
                "info": {"availability": "public"}}

    monkeypatch.setattr(watch, "download", cookie_download)
    watch._download_and_cache("https://youtu.be/abaRace00001", tmp_path / "dl", key=key)
    assert VideoCache(tmp_path / "vc").lookup(key, tmp_path / "w") is None


def test_download_results_carry_the_cookie_fact(tmp_path, monkeypatch):
    import download as download_mod

    def fake_acquire_url(url, out_dir, **kwargs):
        from acquisition import AcquisitionAttempt, AcquisitionResult

        return AcquisitionResult(
            state="success", media_path=str(_media(tmp_path)), subtitle_candidates=[],
            selected_subtitle=None, metadata={"url": url}, source_identity="0" * 64,
            attempts=[AcquisitionAttempt(strategy="default", outcome="success",
                                         failure_class=None, exit_code=0)],
            selected_strategy="default", downloaded=True,
        )

    monkeypatch.setattr(download_mod, "acquire_url", fake_acquire_url)
    monkeypatch.setenv("WATCH_COOKIES_BROWSER", "chrome")
    result = download_mod.download_url("https://youtu.be/cookiefact01", tmp_path / "dl")
    assert result["cookie_used"] is True
    monkeypatch.delenv("WATCH_COOKIES_BROWSER")
    result = download_mod.download_url("https://youtu.be/cookiefact01", tmp_path / "dl2")
    assert result["cookie_used"] is False


def test_symlinked_object_is_evicted_and_reinsertable(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    [obj] = (cache.root / "objects").glob("*.mp4")
    target = tmp_path / "elsewhere.mp4"
    shutil.move(obj, target)
    os.symlink(target, obj)
    assert cache.lookup(IDENTITY, tmp_path / "w1") is None
    assert not obj.is_symlink() and not obj.exists()  # squatter removed
    assert target.exists()  # its TARGET untouched
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    assert cache.lookup(IDENTITY, tmp_path / "w2") is not None


def test_nonfinite_timestamps_read_as_absent(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"][IDENTITY]["stored_at"] = float("inf")   # permanently fresh?
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    assert cache.lookup(IDENTITY, tmp_path / "w") is None


def test_huge_finite_bounds_fall_back_and_inspect_survives(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_VIDEO_CACHE_MAX_GB", "1e308")
    cache = _cache(tmp_path)
    assert cache.max_total_bytes == video_cache.DEFAULT_MAX_TOTAL_BYTES
    assert cache.inspect()["experimental"] is True  # no OverflowError


def test_cache_key_helper_survives_env_file_errors(monkeypatch, capsys):
    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")

    def exploding_read_env_file():
        raise RuntimeError("bad env file")

    monkeypatch.setattr(watch, "read_env_file", exploding_read_env_file)
    assert watch._cache_key_for("https://youtu.be/envfail00001", audio_only=False) is None
    assert "video cache identity failed (RuntimeError)" in capsys.readouterr().err


# --- round-4 regressions ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost./v.mp4",       # trailing-dot normalization
        "https://nas.local./v.mp4",
        "https://127.1/v.mp4",            # legacy short numeric loopback
        "https://0177.0.0.1/v.mp4",       # octal legacy form
        "https://0x7f.0.0.1/v.mp4",       # hex legacy form
        "https://foo.localhost/v.mp4",
        "https://router.home.arpa/v.mp4",
    ],
)
def test_legacy_and_normalized_private_hosts_are_refused(url):
    assert cache_identity(url) is None


def test_missing_cookie_fact_fails_closed(tmp_path, monkeypatch):
    """Only an EXPLICIT cookie_used=False permits retention: an acquisition
    result without the fact (older shape, unexpected path) is never cached."""
    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    clip = _media(tmp_path)
    key = video_cache.cache_identity("https://youtu.be/noFactUrl001")

    monkeypatch.setattr(
        watch, "download",
        lambda s, o, **k: {"video_path": str(clip), "info": {"availability": "public"}},
    )
    watch._download_and_cache("https://youtu.be/noFactUrl001", tmp_path / "dl", key=key)
    assert VideoCache(tmp_path / "vc").lookup(key, tmp_path / "w") is None


def test_acquisition_commands_ignore_ambient_ytdlp_config(tmp_path):
    from acquisition import build_yt_dlp_command

    cmd = build_yt_dlp_command(
        "https://youtu.be/ignorecfg001", str(tmp_path / "video.%(ext)s"),
        audio_only=False, captions_only=False, languages=("en",), cookie_spec=None,
    )
    assert "--ignore-config" in cmd


def test_insert_source_swapped_for_symlink_is_refused(tmp_path):
    cache = _cache(tmp_path)
    target = tmp_path / "outside-target.mp4"
    target.write_bytes(os.urandom(1024))
    link = tmp_path / "clip.mp4"
    os.symlink(target, link)
    assert cache.insert(IDENTITY, link, source_url="https://example.com/v.mp4") is False


def test_lookup_nofollow_fallback_without_o_nofollow(tmp_path, monkeypatch):
    """Windows shape: _O_NOFOLLOW == 0. The lstat+fstat identity fallback must
    still refuse a symlinked object even when its target's bytes would match."""
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://example.com/v.mp4")
    [obj] = (cache.root / "objects").glob("*.mp4")
    target = tmp_path / "matching-target.mp4"
    shutil.move(obj, target)  # target has the MATCHING checksum
    os.symlink(target, obj)
    monkeypatch.setattr(video_cache, "_O_NOFOLLOW", 0)
    assert cache.lookup(IDENTITY, tmp_path / "w") is None


def test_evidence_mode_hit_renders_experimental_marker(tmp_path, monkeypatch, capsys):
    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    clip = _media(tmp_path)
    url = "https://youtu.be/evidencehit1"
    key = video_cache.cache_identity(url)
    assert VideoCache(tmp_path / "vc").insert(key, clip, source_url=url)

    vtt = tmp_path / "video.en.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n", encoding="utf-8")

    def fake_fetch_captions(source, out_dir):
        return {"subtitle_path": str(vtt), "info": {"duration": 900, "availability": "public"},
                "selected_strategy": "default", "attempts": [], "cookie_used": False}

    def fake_compile_evidence(subtitle, video, info, question, out_dir, **kwargs):
        assert Path(video).exists()  # the cached copy is what evidence consumes
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.txt").write_text("EVIDENCE BODY", encoding="utf-8")
        return {"manifest": {}, "report": str(out_dir / "report.txt")}

    import evidence

    monkeypatch.setattr(watch, "fetch_captions", fake_fetch_captions)
    monkeypatch.setattr(evidence, "compile_evidence", fake_compile_evidence)
    monkeypatch.setattr(
        watch, "download",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("hit must not download")),
    )

    class _Args:
        source = url
        question = "what happens?"
        out_dir = str(tmp_path / "work")
        max_frames = 4
        text_budget = 1000
        semantic = "off"
        semantic_endpoint = None
        semantic_model = None
        allow_remote_semantic = False
        export_bundle = None

    assert watch.run_evidence(_Args()) == 0
    out = capsys.readouterr().out
    assert "EVIDENCE BODY" in out
    assert "- **Video cache (experimental):** hit — served checksum-verified local copy" in out


def test_shared_object_corruption_evicts_all_identities_and_reinserts(tmp_path):
    """Round-5 regression: a corrupt object shared by TWO identities must not
    survive via the second identity's refcount, and reinsertion over the
    corrupt name must verify-and-replace, then serve clean bytes."""
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("1" * 64, media, source_url="https://youtu.be/a")
    assert cache.insert("2" * 64, other, source_url="https://youtu.be/b")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.chmod(0o600)
    with obj.open("r+b") as handle:
        handle.write(b"CORRUPT")

    # First identity's hit fails integrity → OBJECT-wide eviction.
    assert cache.lookup("1" * 64, tmp_path / "w1") is None
    assert cache.lookup("2" * 64, tmp_path / "w2") is None  # not resurrected
    assert not list((cache.root / "objects").glob("*.mp4"))

    # Reinsertion stores clean bytes and serves them.
    assert cache.insert("1" * 64, media, source_url="https://youtu.be/a")
    served = cache.lookup("1" * 64, tmp_path / "w3")
    assert served is not None and served.read_bytes() == media.read_bytes()


def test_insert_collision_replaces_corrupt_squatter(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.chmod(0o600)
    with obj.open("r+b") as handle:
        handle.write(b"CORRUPT")  # name collision with WRONG bytes
    # Re-insert under a second identity: the collision path must verify the
    # existing object and replace the corrupt squatter.
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("2" * 64, other, source_url="https://youtu.be/b")
    served = cache.lookup("2" * 64, tmp_path / "w")
    assert served is not None and served.read_bytes() == media.read_bytes()


# --- round-6 regressions ----------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_fifo_squatter_fails_open_instead_of_hanging(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.unlink()
    os.mkfifo(obj)  # a FIFO squatting on the object name
    started = time.time()
    assert cache.lookup(IDENTITY, tmp_path / "w") is None  # miss, not a hang
    assert time.time() - started < video_cache.LOCK_WAIT_SECONDS


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_fifo_source_is_refused(tmp_path):
    cache = _cache(tmp_path)
    fifo = tmp_path / "clip.mp4"
    os.mkfifo(fifo)
    assert cache.insert(IDENTITY, fifo, source_url="https://youtu.be/a") is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_collision_with_matching_digest_but_unsafe_mode_is_replaced(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    [obj] = (cache.root / "objects").glob("*.mp4")
    obj.chmod(0o644)  # matching bytes, WORLD-READABLE — must not be accepted
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("2" * 64, other, source_url="https://youtu.be/b")
    [obj] = (cache.root / "objects").glob("*.mp4")
    assert (obj.stat().st_mode & 0o077) == 0  # replaced with an owner-only copy
    assert cache.lookup("2" * 64, tmp_path / "w") is not None


def test_cold_run_renders_participation_marker(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)
    monkeypatch.setattr(
        _sys, "argv",
        ["watch.py", "https://youtu.be/coldmarker01", "--no-whisper", "--detail", "efficient"],
    )
    assert watch.main() == 0
    out = capsys.readouterr().out
    # A COLD eligible run exercised the experimental path (lookup + insert):
    # CONTRACTS.md requires the marker there too, not only on hits.
    assert "- **Video cache (experimental):** miss — downloaded and stored" in out


# --- round-7 regressions ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",   # nonstandard port
        "https://www.youtube.com/random/path?v=dQw4w9WgXcQ",  # non-canonical path
        "https://www.youtube.com/shorts/OTHERvideo0?v=dQw4w9WgXcQ",  # conflicting ids
        "https://youtu.be/dQw4w9WgXcQ/extra",                 # extra path segment
        "https://youtu.be/dQw4w9WgXcQ?v=OTHERvideo0",         # youtu.be with v conflict
    ],
)
def test_noncanonical_youtube_shapes_never_share_a_key(url):
    assert cache_identity(url) is None


def test_canonical_shapes_still_work():
    assert cache_identity("https://www.youtube.com:443/watch?v=dQw4w9WgXcQ") is not None
    assert cache_identity("https://www.youtube.com/shorts/dQw4w9WgXcQ") is not None
    assert cache_identity("https://www.youtube.com/live/dQw4w9WgXcQ") is not None
    assert cache_identity("https://www.youtube.com/embed/dQw4w9WgXcQ") is not None


def test_marker_survives_store_exception(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)

    def exploding_insert(self, *a, **k):
        raise RuntimeError("store boom")

    monkeypatch.setattr(video_cache.VideoCache, "insert", exploding_insert)
    monkeypatch.setattr(
        _sys, "argv",
        ["watch.py", "https://youtu.be/storeboom001", "--no-whisper", "--detail", "efficient"],
    )
    assert watch.main() == 0
    captured = capsys.readouterr()
    # The run participated in the experimental path — the marker renders even
    # though the store raised (and the failure notice went to stderr).
    assert "- **Video cache (experimental):** miss — downloaded, not stored" in captured.out
    assert "video cache store failed (RuntimeError)" in captured.err


def test_growing_source_is_refused(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path, size=2048)
    real_read = os.read
    grown = {"done": False}

    def growing_read(fd, n):
        block = real_read(fd, n)
        if block and not grown["done"]:
            grown["done"] = True
            with media.open("ab") as handle:  # the source GROWS mid-copy
                handle.write(os.urandom(1024))
        return block

    monkeypatch.setattr(os, "read", growing_read)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    monkeypatch.setattr(os, "read", real_read)
    assert cache.lookup(IDENTITY, tmp_path / "w") is None
    assert not list((cache.root / "objects").glob(".incoming.*"))


def test_source_growing_past_entry_cap_aborts(tmp_path, monkeypatch):
    cache = _cache(tmp_path, max_entry_bytes=4096)
    media = _media(tmp_path, size=2048)
    real_read = os.read

    def feeding_read(fd, n):
        block = real_read(fd, n)
        if block:
            with media.open("ab") as handle:  # keeps growing every read
                handle.write(os.urandom(4096))
        return block

    monkeypatch.setattr(os, "read", feeding_read)
    started = time.time()
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    assert time.time() - started < 10  # bounded, not an endless chase


# --- round-8 regressions ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/dQw4w9WgXcQ?v=",                    # blank v on youtu.be
        "https://www.youtube.com/shorts/dQw4w9WgXcQ?v=",      # blank v on shorts
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=OTHERvideo0",  # duplicate v
        "https://www.youtube.com/watch?v=",                   # empty v
        "https://youtu.be//dQw4w9WgXcQ",                      # repeated slash
        "https://www.youtube.com/shorts//dQw4w9WgXcQ",        # repeated slash
        "https://www.youtube.com:/watch?v=dQw4w9WgXcQ",       # explicit empty port
        "https://www.youtube.com/watch?v=ｄＱｗ４",              # non-ASCII confusables
    ],
)
def test_round8_noncanonical_shapes_are_refused(url):
    assert cache_identity(url) is None


def test_growth_never_consumes_the_headroom_reserve(tmp_path, monkeypatch):
    # Reserve is taken for the PRE-CHECKED size; the copy must abort the
    # moment the source exceeds it, however large the entry cap is.
    cache = _cache(tmp_path, max_entry_bytes=10 * 1024 * 1024 * 1024)
    media = _media(tmp_path, size=1024)
    real_read = os.read
    writes = {"bytes": 0}

    def feeding_read(fd, n):
        block = real_read(fd, n)
        if block:
            with media.open("ab") as handle:
                handle.write(os.urandom(1024 * 1024))
        writes["bytes"] += len(block)
        return block

    monkeypatch.setattr(os, "read", feeding_read)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    monkeypatch.setattr(os, "read", real_read)
    # At most ONE read chunk beyond the reserved size was ever written.
    assert writes["bytes"] <= 1024 + 1024 * 1024 + 1
    assert not list((cache.root / "objects").glob(".incoming.*"))


# --- round-9 regressions ----------------------------------------------------


def test_malformed_ports_are_refused():
    assert cache_identity("https://www.youtube.com:notaport/watch?v=dQw4w9WgXcQ") is None
    assert cache_identity("https://www.youtube.com:99999/watch?v=dQw4w9WgXcQ") is None


def test_non_public_availability_never_stores(cut_clip, tmp_path, monkeypatch):
    import sys as _sys

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    clip = _media(tmp_path)
    key = video_cache.cache_identity("https://youtu.be/unlisted0001")

    for availability in ("unlisted", "private", "needs_auth", None):
        def fake_download(source, out_dir, **kwargs):
            return {"video_path": str(clip), "cookie_used": False,
                    "info": {"availability": availability}}

        monkeypatch.setattr(watch, "download", fake_download)
        watch._download_and_cache("https://youtu.be/unlisted0001", tmp_path / "dl", key=key)
        assert VideoCache(tmp_path / "vc").lookup(key, tmp_path / "w") is None


def test_formerly_public_video_is_not_served_when_no_longer_public(tmp_path):
    import watch

    key = "c" * 64
    cache = VideoCache(tmp_path / "vc")
    media = _media(tmp_path)
    assert cache.insert(key, media, source_url="https://youtu.be/x")  # cached while public
    # The FRESH caption probe now reports it private: the hit must refuse.
    import video_cache as vc
    original = vc.DEFAULT_ROOT
    vc.DEFAULT_ROOT = tmp_path / "vc"
    try:
        dl_private = {"info": {"availability": "private"}, "cookie_used": False}
        assert watch._cache_lookup_media(key, tmp_path / "w", dl_private) is None
        dl_public = {"info": {"availability": "public"}, "cookie_used": False}
        assert watch._cache_lookup_media(key, tmp_path / "w2", dl_public) is not None
    finally:
        vc.DEFAULT_ROOT = original


def test_hit_acquisition_line_separates_media_from_caption_probe(cut_clip, tmp_path, monkeypatch, capsys):
    import sys as _sys

    import watch

    monkeypatch.setenv("WATCH_VIDEO_CACHE", "1")
    monkeypatch.setattr(video_cache, "DEFAULT_ROOT", tmp_path / "vc")
    counter = {"downloads": 0}
    _wire_fake_download(monkeypatch, watch, cut_clip, counter)
    argv = ["watch.py", "https://youtu.be/provenance01", "--no-whisper", "--detail", "efficient"]
    monkeypatch.setattr(_sys, "argv", list(argv))
    assert watch.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(_sys, "argv", list(argv))
    assert watch.main() == 0
    out = capsys.readouterr().out
    assert "- **Acquisition:** media from local video cache; caption probe default" in out


def test_corrupt_index_is_reset_on_disk_and_orphans_swept(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    [obj] = (cache.root / "objects").glob("*.mp4")
    (cache.root / "index.json").write_text("{not json", encoding="utf-8")
    (cache.root / "index.json").chmod(0o600)
    assert cache.lookup(IDENTITY, tmp_path / "w") is None
    # Evict-on-sight: the on-disk index is reset to valid JSON and the
    # now-orphaned object is swept.
    reread = json.loads((cache.root / "index.json").read_text())
    assert reread["entries"] == {}
    assert not obj.exists()


def test_negative_size_rows_read_as_absent_and_bounds_hold(tmp_path):
    cache = _cache(tmp_path, max_total_bytes=10_000)
    media = _media(tmp_path)
    assert cache.insert("1" * 64, media, source_url="https://youtu.be/a")
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"]["1" * 64]["size"] = -10_000_000  # dishonest negative row
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    assert cache.lookup("1" * 64, tmp_path / "w") is None  # read as absent
    assert cache.inspect()["total_bytes"] >= 0


def test_lock_symlink_squatter_without_o_nofollow(tmp_path, monkeypatch):
    monkeypatch.setattr(video_cache, "_O_NOFOLLOW", 0)
    cache = _cache(tmp_path)
    cache._prepare()
    victim = tmp_path / "victim-lockfile"
    victim.write_text("innocent")
    os.symlink(victim, cache.root / ".lock")
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    assert victim.read_text() == "innocent"  # never followed


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_lock_special_file_squatter_without_o_nofollow(tmp_path, monkeypatch):
    monkeypatch.setattr(video_cache, "_O_NOFOLLOW", 0)
    cache = _cache(tmp_path)
    cache._prepare()
    os.mkfifo(cache.root / ".lock")
    media = _media(tmp_path)
    started = time.time()
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    assert time.time() - started < 10  # O_NONBLOCK: no hang on the FIFO


# --- round-10 regressions ---------------------------------------------------


def test_hit_probe_matrix_fails_closed(tmp_path):
    import watch

    key = "d" * 64
    cache = VideoCache(tmp_path / "vc")
    media = _media(tmp_path)
    assert cache.insert(key, media, source_url="https://youtu.be/x")
    import video_cache as vc
    original = vc.DEFAULT_ROOT
    vc.DEFAULT_ROOT = tmp_path / "vc"
    try:
        refused = [
            None,                                                   # no probe at all
            {},                                                     # empty probe
            {"info": {"availability": "public"}},                   # missing cookie fact
            {"info": {"availability": "public"}, "cookie_used": True},   # authenticated probe
            {"info": {}, "cookie_used": False},                     # missing availability
            {"info": {"availability": "unlisted"}, "cookie_used": False},
            {"info": "public", "cookie_used": False},  # malformed: info not a dict
            {"info": ["public"], "cookie_used": False},
        ]
        for i, dl in enumerate(refused):
            assert watch._cache_lookup_media(key, tmp_path / f"w{i}", dl) is None, dl
        ok = {"info": {"availability": "public"}, "cookie_used": False}
        assert watch._cache_lookup_media(key, tmp_path / "wok", ok) is not None
    finally:
        vc.DEFAULT_ROOT = original


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
@pytest.mark.parametrize("nofollow", [True, False])
def test_unsafe_mode_lock_is_refused_on_both_branches(tmp_path, monkeypatch, nofollow):
    if not nofollow:
        monkeypatch.setattr(video_cache, "_O_NOFOLLOW", 0)
    cache = _cache(tmp_path)
    cache._prepare()
    lock = cache.root / ".lock"
    lock.write_text("")
    lock.chmod(0o666)  # group/other-writable lock: never trusted
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False


def test_index_size_bounds_zero_and_over_cap_read_as_absent(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    index = json.loads((cache.root / "index.json").read_text())
    good = dict(index["entries"][IDENTITY])
    index["entries"][IDENTITY] = {**good, "size": 0}
    index["entries"]["e" * 64] = {**good, "size": cache.max_entry_bytes + 1}
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    # The READ BOUNDARY itself must drop both rows — not a later size
    # mismatch during lookup.
    assert cache._read_index()["entries"] == {}
    assert cache.lookup(IDENTITY, tmp_path / "w1") is None
    assert cache.lookup("e" * 64, tmp_path / "w2") is None


def test_underreported_index_size_still_triggers_lru_by_real_size(tmp_path):
    cache = _cache(tmp_path, max_total_bytes=10_000)
    big_a = _media(tmp_path, "a.mp4", 6_000)
    big_b = _media(tmp_path, "b.mp4", 6_000)
    assert cache.insert("1" * 64, big_a, source_url="https://youtu.be/a")
    # Lie in the index: claim entry 1 is tiny. Real objects are 6000+6000 >
    # 10000, so the SECOND insert must still evict by verified st_size.
    index = json.loads((cache.root / "index.json").read_text())
    index["entries"]["1" * 64]["size"] = 1
    (cache.root / "index.json").write_text(json.dumps(index))
    (cache.root / "index.json").chmod(0o600)
    time.sleep(0.02)
    assert cache.insert("2" * 64, big_b, source_url="https://youtu.be/b")
    # THE INSERT's LRU pass must have evicted by verified st_size — assert on
    # the raw index and the measured object bytes BEFORE any lookup could
    # mask it with its own eviction.
    raw = json.loads((cache.root / "index.json").read_text())
    assert list(raw["entries"].keys()) == ["2" * 64]
    on_disk = sum(
        o.stat().st_size for o in (cache.root / "objects").glob("*.mp4")
    )
    assert on_disk <= cache.max_total_bytes
    assert cache.lookup("2" * 64, tmp_path / "w2") is not None


# --- round-12 regressions ---------------------------------------------------


def test_failed_index_commit_leaves_no_untracked_object(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path)

    def exploding_write_index(self, data):
        raise OSError("index commit failed")

    monkeypatch.setattr(VideoCache, "_write_index", exploding_write_index)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    monkeypatch.undo()
    # The freshly published object was rolled back — nothing untracked.
    assert not list((cache.root / "objects").glob("*.mp4"))
    assert cache.inspect()["entry_count"] == 0


def test_failed_second_identity_commit_preserves_shared_object(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    other = tmp_path / "same.mp4"
    shutil.copyfile(media, other)
    assert cache.insert("1" * 64, media, source_url="https://youtu.be/a")

    def exploding_write_index(self, data):
        raise OSError("index commit failed")

    monkeypatch.setattr(VideoCache, "_write_index", exploding_write_index)
    assert cache.insert("2" * 64, other, source_url="https://youtu.be/b") is False
    monkeypatch.undo()
    # Identity 1's shared object survived the failed second commit.
    assert cache.lookup("1" * 64, tmp_path / "w") is not None


# --- round-13 regressions ---------------------------------------------------


def test_failed_insert_after_planned_lru_eviction_preserves_victim(tmp_path, monkeypatch):
    """Deletions are deferred past the index commit: if B's insert plans A's
    LRU eviction and the commit then FAILS, A's object and on-disk index row
    must both survive."""
    cache = _cache(tmp_path, max_total_bytes=10_000)
    a = _media(tmp_path, "a.mp4", 6_000)
    b = _media(tmp_path, "b.mp4", 6_000)
    assert cache.insert("1" * 64, a, source_url="https://youtu.be/a")
    time.sleep(0.02)

    real_write = VideoCache._write_index
    def exploding_write_index(self, data):
        raise OSError("commit failed")

    monkeypatch.setattr(VideoCache, "_write_index", exploding_write_index)
    assert cache.insert("2" * 64, b, source_url="https://youtu.be/b") is False
    monkeypatch.setattr(VideoCache, "_write_index", real_write)
    # A is fully intact and servable; B's fresh object was rolled back.
    assert cache.lookup("1" * 64, tmp_path / "w") is not None
    assert len(list((cache.root / "objects").glob("*.mp4"))) == 1


def test_failed_replacement_of_unreferenced_squatter_leaves_no_orphan(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    # Plant an unreferenced INVALID squatter at the digest name the insert
    # will use (no index row references it).
    import hashlib as _hashlib

    digest = _hashlib.sha256(media.read_bytes()).hexdigest()
    cache._prepare()
    squatter = cache.root / "objects" / f"{digest}.mp4"
    squatter.write_bytes(b"WRONG BYTES")
    squatter.chmod(0o600)

    def exploding_write_index(self, data):
        raise OSError("commit failed")

    monkeypatch.setattr(VideoCache, "_write_index", exploding_write_index)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    monkeypatch.undo()
    # The replaced-but-uncommitted object was rolled back — no orphan.
    assert not squatter.exists()


@pytest.mark.skipif(os.name == "nt", reason="ancestor-symlink walk is a POSIX guarantee; Windows uses the profile-root ACL boundary")
def test_symlinked_cache_ancestor_is_refused(tmp_path):
    real = tmp_path / "real-parent"
    real.mkdir()
    linked = tmp_path / "linked-parent"
    os.symlink(real, linked)
    cache = VideoCache(linked / "video-cache")
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a") is False
    assert cache.lookup(IDENTITY, tmp_path / "w") is None


# --- round-14 regressions ---------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="ancestor-symlink walk is a POSIX guarantee; Windows uses the profile-root ACL boundary")
def test_inspect_and_purge_refuse_symlinked_ancestors(tmp_path):
    # Seed VALID cache data on the target side first: the refusal must hold
    # even when the link points at a perfectly healthy cache, and not one
    # byte behind the link may change.
    real = tmp_path / "real-parent"
    target_cache = VideoCache(real / "video-cache")
    media = _media(tmp_path)
    assert target_cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    sentinel = real / "sentinel.txt"
    sentinel.write_text("precious")

    def snapshot():
        return sorted(
            (str(p.relative_to(real)), p.read_bytes() if p.is_file() else b"")
            for p in real.rglob("*")
        )

    before = snapshot()
    linked = tmp_path / "linked-parent"
    os.symlink(real, linked)
    cache = VideoCache(linked / "video-cache")
    assert cache.inspect()["entry_count"] == 0   # refuses the VALID data
    assert cache.purge() is False
    assert snapshot() == before                   # every target byte intact
    assert sentinel.read_text() == "precious"
    # The real path still serves normally.
    assert target_cache.lookup(IDENTITY, tmp_path / "w") is not None


def test_purge_clears_contents_but_keeps_root_and_lock(tmp_path):
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    assert cache.purge() is True
    assert cache.root.exists()  # lock-bearing root survives
    assert not (cache.root / "index.json").exists()
    assert not list((cache.root / "objects").glob("*"))
    # And the cache still works afterwards.
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    assert cache.lookup(IDENTITY, tmp_path / "w") is not None


@pytest.mark.skipif(os.name == "nt", reason="flock branch")
def test_purge_serializes_with_a_live_writer(tmp_path, monkeypatch):
    import fcntl

    monkeypatch.setattr(video_cache, "LOCK_WAIT_SECONDS", 0.1)
    cache = _cache(tmp_path)
    media = _media(tmp_path)
    assert cache.insert(IDENTITY, media, source_url="https://youtu.be/a")
    holder_fd = os.open(cache.root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder_fd, fcntl.LOCK_EX)
    try:
        # A live writer holds the lock: purge must NOT shred anything.
        assert cache.purge() is False
        assert cache.lookup is not None
    finally:
        os.close(holder_fd)
    assert cache.lookup(IDENTITY, tmp_path / "w") is not None  # intact
    assert cache.purge() is True  # succeeds once the writer is gone
