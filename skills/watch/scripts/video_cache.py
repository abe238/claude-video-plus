#!/usr/bin/env python3
"""Opt-in content-addressed video cache (WATCH_VIDEO_CACHE=1).

Idea from m1crodevil/hermes-video's `~/.cache/watch/<sha256>.mp4` store,
rebuilt against this repo's no-media-persistence posture: the cache is a
SEPARATE, explicitly opted-in media store — `EvidenceState`'s unconditional
media refusal is untouched, and with the flag unset nothing here ever runs.

Design contract (Codex-hardened, docs/plans/2026-08-18-fork-deep-pass.md P2):

- URL-only, HTTPS-only. Local files already persist at their own path and
  are never duplicated into the cache.
- Cookie-authenticated, signed, private, and credential-bearing sources are
  EXCLUDED OUTRIGHT — no consent path, because a cached copy outlives the
  authorization that fetched it. Exclusion is property-based: any configured
  cookie spec disables caching entirely; userinfo, fragments, or any query
  parameter outside a small benign allowlist (even on YouTube) refuses the
  identity. YouTube URLs reduce to their video id.
- The lookup is source-index → verified content digest (recomputed sha256 on
  EVERY hit, through an O_NOFOLLOW descriptor), because a true digest is
  unknowable pre-download and `acquisition.source_identity` collapses
  query-form YouTube URLs.
- Index values are untrusted on read: digests must be lowercase hex-64 and
  suffixes allowlisted BEFORE any path is built, and every object path must
  resolve to a direct child of the objects directory — a poisoned index can
  never stat, hash, or unlink outside the cache.
- Objects are refcounted across identities (content addressing dedupes), so
  evicting one identity never breaks another that shares the digest.
- Owner-only storage (0700/0600, Windows profile-root guard, no symlinks),
  exclusive O_NOFOLLOW temporaries with full try/finally lifecycles, stale
  incoming sweep, an OS-backed advisory lock (kernel-released on process
  death — no staleness heuristics, no steal races), atomic index
  replacement; malformed index rows read as absent, and integrity
  failures evict the object and every identity referencing it.
- Bounds: per-entry max (oversized bypass), unique-object total LRU, TTL,
  disk-headroom guard.
- Fail-open everywhere: ANY cache failure prints one stderr notice and the
  run downloads fresh. Consent and WATCH_MAX_FILESIZE semantics on misses
  are untouched.

Inspect: python3 video_cache.py --inspect   Purge: python3 video_cache.py --purge
(`lifecycle.py --purge-cache` removes the whole ~/.cache/watch root too.)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

if os.name == "nt":  # pragma: no cover - exercised on the Windows CI leg
    import msvcrt
else:
    import fcntl

try:
    from config import read_env_file  # same-dir sibling
except Exception:  # pragma: no cover - standalone CLI use outside the skill dir
    def read_env_file() -> dict:
        return {}


DEFAULT_ROOT = Path.home() / ".cache" / "watch" / "video-cache"
INDEX_NAME = "index.json"
OBJECTS_DIR = "objects"
CACHE_SCHEMA = 1

_GIB = 1024 * 1024 * 1024


def _env_nonnegative_float(name: str, default: float, file_values: dict | None = None) -> float:
    """Environment first, then ~/.config/watch/.env; malformed, negative, or
    non-finite (inf/nan would overflow the byte math) falls back to default."""
    raw = os.environ.get(name)
    if raw is None and file_values:
        raw = file_values.get(name)
    try:
        value = float(raw if raw is not None else "")
        # Finite AND sane: 1e308 GiB would overflow the int() byte math.
        if 0 <= value <= 1e6 and math.isfinite(value):
            return value
        return default
    except (TypeError, ValueError):
        return default


DEFAULT_MAX_TOTAL_BYTES = int(10 * _GIB)     # WATCH_VIDEO_CACHE_MAX_GB
DEFAULT_MAX_ENTRY_BYTES = int(2 * _GIB)      # WATCH_VIDEO_CACHE_MAX_ENTRY_GB
DEFAULT_TTL_SECONDS = 30 * 24 * 3600         # WATCH_VIDEO_CACHE_TTL_DAYS
# Never fill the disk: an insert must leave at least this much free.
DISK_HEADROOM_BYTES = int(5 * _GIB)
LOCK_WAIT_SECONDS = 5.0
INCOMING_STALE_SECONDS = 3600.0

_IS_WINDOWS = os.name == "nt"
_POSIX_MODE_BITS = not _IS_WINDOWS

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
# Benign, non-authorizing YouTube parameters. ANYTHING else — token, signature,
# pot, key, whatever arrives next — refuses the identity. An allowlist of the
# harmless is the property-based inverse of a denylist of the harmful.
_YOUTUBE_BENIGN_PARAMS = {"v", "t", "list", "index", "si", "feature", "app", "ab_channel", "start", "end"}
_ALLOWED_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".opus"}
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
# ASCII-only id alphabet: str.isalnum() would admit Unicode confusables.
_YOUTUBE_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
_YOUTUBE_ID_PATH_RE = re.compile(r"/(?P<id>[A-Za-z0-9_-]+)")
_YOUTUBE_KIND_PATH_RE = re.compile(r"/(?:shorts|live|embed)/(?P<id>[A-Za-z0-9_-]+)")


def cache_enabled(file_values: dict | None = None) -> bool:
    """Opt-in only: WATCH_VIDEO_CACHE truthy in the environment or config file."""
    raw = os.environ.get("WATCH_VIDEO_CACHE")
    if raw is None and file_values:
        raw = file_values.get("WATCH_VIDEO_CACHE")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def cache_identity(url: str, *, audio_only: bool = False, cookie_spec: str | None = None) -> str | None:
    """Canonical cache key for a source URL, or None when caching is refused."""
    if cookie_spec:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() != "https":
        return None
    if parts.username or parts.password or parts.fragment:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None

    if host in _YOUTUBE_HOSTS or host == "youtu.be":
        try:
            port = parts.port  # raises ValueError on malformed ports
        except ValueError:
            return None
        if port not in (None, 443) or parts.netloc.endswith(":"):
            return None  # nonstandard, malformed, or explicit-empty port
        params = parse_qs(parts.query, keep_blank_values=True)
        if any(key not in _YOUTUBE_BENIGN_PARAMS for key in params):
            return None  # unrecognized parameter: possibly authorization-bearing
        # STRICT canonical shapes, matched on the RAW path (repeated slashes
        # are not canonical), with presence/cardinality rules on `v`: any URL
        # outside these shapes must never share a key with the video it
        # happens to mention.
        video_id = ""
        if parts.path == "/watch" and host != "youtu.be":
            values = params.get("v") or []
            if len(values) == 1 and values[0]:
                video_id = values[0]
        elif "v" not in params:
            if host == "youtu.be":
                match = _YOUTUBE_ID_PATH_RE.fullmatch(parts.path)
                video_id = match.group("id") if match else ""
            else:
                match = _YOUTUBE_KIND_PATH_RE.fullmatch(parts.path)
                video_id = match.group("id") if match else ""
        if not video_id or not _YOUTUBE_ID_RE.fullmatch(video_id):
            return None
        canonical = {"kind": "youtube", "id": video_id, "audio_only": bool(audio_only)}
    else:
        # v1.5.5 scope: caching is restricted to the known-public YouTube
        # host set above. A generic HTTPS host cannot be proven public
        # lexically — DNS or /etc/hosts can map any FQDN (home.arpa included)
        # to loopback/RFC1918 space — so rather than resolve-and-hope, the
        # cache refuses. Widening to generic hosts is a future packet that
        # must carry address-resolution validation at lookup AND insert.
        return None
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _owner_only_stat(info: os.stat_result, *, directory: bool) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return False
    if directory and not stat.S_ISDIR(info.st_mode):
        return False
    if not directory and not stat.S_ISREG(info.st_mode):
        return False
    if _POSIX_MODE_BITS and info.st_mode & 0o077:
        return False
    getuid = getattr(os, "getuid", None)
    return getuid is None or info.st_uid == getuid()


def _owner_only(path: Path, *, directory: bool) -> bool:
    try:
        return _owner_only_stat(path.lstat(), directory=directory)
    except OSError:
        return False


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def _open_read_nofollow(path: Path) -> int:
    """Open for reading: never follows a symlink, never blocks, and the
    descriptor is PROVEN a regular file before it is returned. O_NONBLOCK
    makes a FIFO squatter fail instead of hanging the open under the cache
    lock (harmless on regular files); where O_NOFOLLOW is missing (Windows),
    lstat + fstat inode identity substitutes."""
    if _O_NOFOLLOW:
        fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise OSError("refusing non-regular file")
        return fd
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise OSError("refusing non-regular file")
    fd = os.open(path, os.O_RDONLY | _O_NONBLOCK)
    try:
        after = os.fstat(fd)
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(after.st_mode)
        ):
            raise OSError("file changed between lstat and open")
    except OSError:
        os.close(fd)
        raise
    return fd


def _notice(operation: str, exc: BaseException) -> None:
    print(
        f"[watch] video cache {operation} failed ({type(exc).__name__}); continuing without cache",
        file=sys.stderr,
    )


class CacheUnavailable(RuntimeError):
    """Internal signal; every public entry point converts it to a miss/no-op."""


class VideoCache:
    def __init__(
        self,
        root: Path | str | None = None,
        *,
        max_total_bytes: int | None = None,
        max_entry_bytes: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        # Resolved at CALL time (not def time) so tests can repoint
        # DEFAULT_ROOT and production never writes outside its own root.
        self.root = Path(root).expanduser() if root is not None else DEFAULT_ROOT
        try:
            file_values = read_env_file()
        except Exception:
            file_values = {}
        if max_total_bytes is None:
            max_total_bytes = int(
                _env_nonnegative_float("WATCH_VIDEO_CACHE_MAX_GB", 10.0, file_values) * _GIB
            ) or DEFAULT_MAX_TOTAL_BYTES
        if max_entry_bytes is None:
            max_entry_bytes = int(
                _env_nonnegative_float("WATCH_VIDEO_CACHE_MAX_ENTRY_GB", 2.0, file_values) * _GIB
            ) or DEFAULT_MAX_ENTRY_BYTES
        if ttl_seconds is None:
            ttl_seconds = int(
                _env_nonnegative_float("WATCH_VIDEO_CACHE_TTL_DAYS", 30.0, file_values) * 24 * 3600
            ) or DEFAULT_TTL_SECONDS
        self.max_total_bytes = max_total_bytes
        self.max_entry_bytes = max_entry_bytes
        self.ttl_seconds = ttl_seconds

    # -- storage plumbing ---------------------------------------------------

    def _validate_tree(self) -> None:
        """Non-creating root/ancestor validation shared by every entry point
        (lookup/insert via _prepare, and inspect/purge directly): no
        symlinked ancestors (a link above the root redirects every write),
        and the Windows profile-root boundary."""
        probe = self.root
        while probe != probe.parent:
            if probe.is_symlink():
                raise CacheUnavailable(f"cache path ancestor is a symlink: {probe.name}")
            probe = probe.parent
        if _IS_WINDOWS:
            try:
                self.root.resolve().relative_to(Path.home().resolve())
            except ValueError:
                raise CacheUnavailable("video cache must live under the user profile")

    def _prepare(self) -> None:
        self._validate_tree()  # THE policy chokepoint (ancestors + Windows profile)
        for directory in (self.root, self.root / OBJECTS_DIR):
            if directory.exists() or directory.is_symlink():
                if not _owner_only(directory, directory=True):
                    raise CacheUnavailable("unsafe cache directory permissions or type")
                continue
            try:
                directory.mkdir(parents=True, mode=0o700)
                os.chmod(directory, 0o700)
            except FileExistsError:
                pass
            if not _owner_only(directory, directory=True):
                raise CacheUnavailable("could not create an owner-only cache directory")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """OS-backed advisory lock on a lock FILE: released automatically on
        process death, so there is no staleness heuristic and therefore no
        steal race between contenders — the kernel serializes them."""
        self._prepare()
        lock_path = self.root / ".lock"
        if not _O_NOFOLLOW:
            # No O_NOFOLLOW (Windows): an absent lock is created with O_EXCL
            # (a symlink planted after our lstat makes creation FAIL, not
            # follow), an existing one is validated by lstat, and after every
            # open the pathname must still identify the very inode we hold.
            try:
                fd = os.open(
                    lock_path,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | _O_NONBLOCK,
                    0o600,
                )
            except FileExistsError:
                before = os.lstat(lock_path)
                if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                    raise CacheUnavailable("cache lock is not a regular file")
                fd = os.open(lock_path, os.O_RDWR | _O_NONBLOCK)
            try:
                held = os.fstat(fd)
                current = os.lstat(lock_path)
                if (
                    not _owner_only_stat(held, directory=False)
                    or stat.S_ISLNK(current.st_mode)
                    or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)
                ):
                    raise CacheUnavailable("cache lock is not our owner-only regular file")
            except (OSError, CacheUnavailable):
                os.close(fd)
                raise
        else:
            fd = os.open(
                lock_path, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW | _O_NONBLOCK, 0o600
            )
            try:
                held = os.fstat(fd)
                if not _owner_only_stat(held, directory=False):
                    raise CacheUnavailable("cache lock is not an owner-only regular file")
            except (OSError, CacheUnavailable):
                os.close(fd)
                raise
        if _IS_WINDOWS:  # pragma: no cover - Windows CI leg
            # msvcrt.locking locks a byte RANGE at the file pointer; on a
            # freshly-created empty lock file locking [0,1) fails, so ensure
            # one byte exists and lock it deterministically at offset 0.
            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
            except OSError:
                pass
            os.lseek(fd, 0, os.SEEK_SET)
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        try:
            while True:
                try:
                    if _IS_WINDOWS:  # pragma: no cover - Windows CI leg
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CacheUnavailable("timed out waiting for cache lock")
                    time.sleep(0.02)
            try:
                yield
            finally:
                try:
                    if _IS_WINDOWS:  # pragma: no cover
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(fd)

    def _index_path(self) -> Path:
        return self.root / INDEX_NAME

    def _read_index(self) -> dict:
        """Read and validate; self._index_dirty marks on-disk content that was
        invalid or partially dropped, so mutating operations (already under
        the lock) can atomically reset the file and sweep orphans instead of
        leaving corrupt bytes on disk indefinitely."""
        self._index_dirty = False
        empty = {"schema_version": CACHE_SCHEMA, "entries": {}}
        path = self._index_path()
        if not path.exists():
            return empty
        if not _owner_only(path, directory=False):
            self._index_dirty = True
            return empty
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._index_dirty = True
            return empty
        if not isinstance(data, dict) or data.get("schema_version") != CACHE_SCHEMA:
            self._index_dirty = True
            return empty
        if not isinstance(data.get("entries"), dict):
            self._index_dirty = True
            return empty
        # Scalar validation at the boundary: a poisoned entry (size: [],
        # stored_at: {}) must read as absent, never raise later.
        clean: dict = {}
        for identity, entry in data["entries"].items():
            def _finite_number(value: object) -> bool:
                return (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                )

            if (
                isinstance(entry, dict)
                and isinstance(entry.get("digest"), str)
                and isinstance(entry.get("suffix"), str)
                and isinstance(entry.get("size"), int)
                and not isinstance(entry.get("size"), bool)
                and 0 < entry.get("size") <= self.max_entry_bytes
                and _finite_number(entry.get("stored_at"))
                and _finite_number(entry.get("last_used"))
            ):
                clean[identity] = entry
        if len(clean) != len(data["entries"]):
            self._index_dirty = True
        data["entries"] = clean
        return data

    def _exclusive_temporary(self, directory: Path, prefix: str) -> tuple[int, Path]:
        """0600, O_EXCL, O_NOFOLLOW, unpredictable name — a pre-planted
        symlink or squatter file can never be followed or reused."""
        path = directory / f"{prefix}{os.getpid()}.{uuid.uuid4().hex}.tmp"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600)
        return fd, path

    def _write_index(self, data: dict) -> None:
        fd, temporary = self._exclusive_temporary(self.root, f".{INDEX_NAME}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._index_path())
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _object_path(self, digest: str, suffix: str) -> Path | None:
        """Validated object path: hex-64 digest, allowlisted suffix, and a
        direct child of the objects dir — a poisoned index cannot target
        anything else for stat/hash/unlink."""
        if not _DIGEST_RE.fullmatch(digest) or suffix not in _ALLOWED_SUFFIXES:
            return None
        objects = self.root / OBJECTS_DIR
        candidate = objects / f"{digest}{suffix}"
        if candidate.parent != objects or candidate.name != f"{digest}{suffix}":
            return None
        return candidate

    @staticmethod
    def _refcount(entries: dict, digest: str, suffix: str) -> int:
        return sum(
            1
            for entry in entries.values()
            if isinstance(entry, dict)
            and entry.get("digest") == digest
            and entry.get("suffix") == suffix
        )

    @staticmethod
    def _delete(obj: Path) -> None:
        try:
            # A symlink squatting on the object name is itself removed (the
            # path is a validated direct child — unlink touches only the link,
            # never its target), or the digest stays permanently poisoned.
            obj.unlink(missing_ok=True)
        except OSError:
            pass

    def _evict_object(self, data: dict, digest: str, suffix: str, deferred: list | None = None) -> None:
        """Integrity eviction: the OBJECT is bad, so every identity that
        references it is a lie — drop them all and remove the validated name.
        With `deferred`, removal is POSTPONED until after the index commits
        (a failed commit must never orphan the old index against a deleted
        object); without it, removal is immediate (corrupt-object contexts,
        where the bytes are wrong under any index)."""
        for identity in [
            key
            for key, entry in data["entries"].items()
            if isinstance(entry, dict)
            and entry.get("digest") == digest
            and entry.get("suffix") == suffix
        ]:
            data["entries"].pop(identity, None)
        obj = self._object_path(digest, suffix)
        if obj is not None:
            if deferred is not None:
                deferred.append(obj)
            else:
                self._delete(obj)

    def _evict(self, data: dict, identity: str, deferred: list | None = None) -> None:
        entry = data["entries"].pop(identity, None)
        if not isinstance(entry, dict):
            return
        digest = str(entry.get("digest") or "")
        suffix = str(entry.get("suffix") or "")
        obj = self._object_path(digest, suffix)
        if obj is None:
            return  # invalid names never become unlink targets
        if self._refcount(data["entries"], digest, suffix) > 0:
            return  # other identities still reference this object
        if deferred is not None:
            deferred.append(obj)
        else:
            self._delete(obj)

    # -- public API (every failure is a notice + miss / no-op) --------------

    def lookup(self, identity: str, work_dir: Path) -> Path | None:
        """Serve a verified copy of a cached video into work_dir, or None.

        The stored object is opened ONCE with O_NOFOLLOW; type, size, and
        sha256 are all taken through that descriptor, so a swap between
        checks cannot serve different bytes than were verified."""
        try:
            with self._locked():
                data = self._read_index()
                if getattr(self, "_index_dirty", False):
                    # Evict-on-sight for corrupt on-disk state: reset the
                    # index atomically and sweep now-orphaned objects.
                    self._enforce_bounds(data, time.time())
                    self._write_index(data)
                entry = data["entries"].get(identity)
                if not isinstance(entry, dict):
                    return None
                digest = str(entry.get("digest") or "")
                suffix = str(entry.get("suffix") or "")
                obj = self._object_path(digest, suffix)
                now = time.time()
                try:
                    fresh = now - float(entry.get("stored_at") or 0) <= self.ttl_seconds
                except (TypeError, ValueError):
                    fresh = False
                if obj is None or not fresh:
                    self._evict(data, identity)
                    self._write_index(data)
                    return None

                served: Path | None = None
                try:
                    fd = _open_read_nofollow(obj)
                except OSError:
                    fd = -1
                if fd >= 0:
                    try:
                        info = os.fstat(fd)
                        if (
                            _owner_only_stat(info, directory=False)
                            and info.st_size == int(entry.get("size") or -1)
                        ):
                            work_dir.mkdir(parents=True, exist_ok=True)
                            hasher = hashlib.sha256()
                            copy_fd, copy_tmp = self._exclusive_temporary(work_dir, ".video.")
                            replaced = False
                            try:
                                with os.fdopen(copy_fd, "wb") as out:
                                    while True:
                                        block = os.read(fd, 1024 * 1024)
                                        if not block:
                                            break
                                        hasher.update(block)
                                        out.write(block)
                                    out.flush()
                                    os.fsync(out.fileno())
                                if hasher.hexdigest() == digest:
                                    destination = work_dir / f"video{suffix}"
                                    # Atomic replacement: a pre-existing
                                    # destination (symlink included) is
                                    # replaced, never followed.
                                    os.replace(copy_tmp, destination)
                                    replaced = True
                                    served = destination
                            finally:
                                if not replaced:
                                    try:
                                        copy_tmp.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                    finally:
                        os.close(fd)
                if served is None:
                    # Integrity failure: the object itself is bad — every
                    # identity referencing it must go, or a second identity
                    # keeps resurrecting the corrupt bytes forever.
                    self._evict_object(data, digest, suffix)
                    self._write_index(data)
                    return None
                entry["last_used"] = now
                self._write_index(data)
                return served
        except Exception as exc:
            _notice("lookup", exc)
            return None

    def insert(self, identity: str, media_path: Path, *, source_url: str) -> bool:
        """Store a downloaded video under its content digest. Best-effort:
        False means the run simply keeps its normal lifecycle."""
        try:
            media_path = Path(media_path)
            suffix = media_path.suffix.lower()
            if suffix not in _ALLOWED_SUFFIXES:
                return False
            # Defense in depth for the index contents: only a canonical,
            # query-free URL shape (plus a validated YouTube id) is recorded,
            # whatever the caller passes.
            url_parts = urlsplit(source_url)
            if url_parts.username or url_parts.password:
                return False
            # CONTRACTS.md: query/fragment are STRIPPED from anything the
            # store records — no reconstruction, not even a video id.
            recorded_url = f"{url_parts.scheme}://{url_parts.netloc}{url_parts.path}"
            # The SOURCE only needs to be a real regular file (yt-dlp writes
            # 0644 under a normal umask); the owner-only guarantee applies to
            # the STORED object, created 0600 below. Open once, no-follow,
            # and validate through the descriptor so the pathname can't be
            # swapped for a symlink between check and copy.
            try:
                source_fd = _open_read_nofollow(media_path)
            except OSError:
                return False
            size = os.fstat(source_fd).st_size
            if size == 0 or size > self.max_entry_bytes:
                os.close(source_fd)
                return False  # oversized bypass: not an error
            source_closed = False
            try:
                with self._locked():
                    usage = shutil.disk_usage(str(self.root))
                    if usage.free - size < DISK_HEADROOM_BYTES:
                        return False
                    # Snapshot the index BEFORE publishing so a failed commit
                    # can tell a fresh object from one other rows already
                    # reference (dedupe) — the fresh one must not linger
                    # untracked, the shared one must not be destroyed.
                    data = self._read_index()
                    objects = self.root / OBJECTS_DIR
                    digest_hash = hashlib.sha256()
                    tmp_fd, temporary = self._exclusive_temporary(objects, ".incoming.")
                    try:
                        copied = 0
                        with os.fdopen(tmp_fd, "wb") as dst:
                            while True:
                                block = os.read(source_fd, 1024 * 1024)
                                if not block:
                                    break
                                copied += len(block)
                                if copied > size:
                                    # The headroom reservation was for `size`
                                    # bytes: a source that GREW past it must
                                    # not eat the reserve — abort immediately.
                                    return False
                                digest_hash.update(block)
                                dst.write(block)
                            dst.flush()
                            os.fsync(dst.fileno())
                        # Stability: the bytes stored must be exactly the
                        # size that was bounds-checked — a still-growing or
                        # truncated source is refused, and size/LRU/headroom
                        # accounting stays truthful.
                        if copied != size or os.fstat(source_fd).st_size != size:
                            return False
                        digest = digest_hash.hexdigest()
                        obj = self._object_path(digest, suffix)
                        if obj is None:
                            return False
                        pre_referenced = self._refcount(data["entries"], digest, suffix) > 0
                        created_fresh = False
                        replaced_squatter = False
                        try:
                            os.link(temporary, obj)  # atomic no-replace
                            created_fresh = True
                        except FileExistsError:
                            # Same NAME already stored — but never assume it
                            # is the right inode: it must be an owner-only
                            # regular file of the expected size whose bytes
                            # hash to the digest. Anything less is replaced
                            # ATOMICALLY (os.replace of our verified temp —
                            # no unlink/link crash window).
                            valid = False
                            try:
                                check_fd = _open_read_nofollow(obj)
                                try:
                                    existing = os.fstat(check_fd)
                                    if (
                                        _owner_only_stat(existing, directory=False)
                                        and existing.st_size == size
                                    ):
                                        check = hashlib.sha256()
                                        while True:
                                            block = os.read(check_fd, 1024 * 1024)
                                            if not block:
                                                break
                                            check.update(block)
                                        valid = check.hexdigest() == digest
                                finally:
                                    os.close(check_fd)
                            except OSError:
                                valid = False
                            if not valid:
                                os.replace(temporary, obj)
                                replaced_squatter = True
                    finally:
                        # The COMPLETE temporary lifecycle: a failure anywhere
                        # in the copy leaves nothing behind.
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                    now = time.time()
                    data["entries"][identity] = {
                        "digest": digest,
                        "suffix": suffix,
                        "size": size,
                        "stored_at": now,
                        "last_used": now,
                        "source_url": recorded_url,
                    }
                    # Deletions are DEFERRED past the index commit: bounds
                    # enforcement here only PLANS removals, so a failed commit
                    # can never leave the old on-disk index pointing at
                    # already-deleted objects.
                    deferred: list = []
                    self._enforce_bounds(data, now, deferred)
                    try:
                        self._write_index(data)
                    except Exception:
                        # Undo only THIS insertion's publication, and only
                        # when the pre-insert snapshot did not reference it
                        # (a replaced invalid squatter with pre-existing
                        # references keeps the now-valid bytes).
                        if (created_fresh or replaced_squatter) and not pre_referenced:
                            try:
                                obj.unlink(missing_ok=True)
                            except OSError:
                                pass
                        raise
                    for stale in deferred:
                        self._delete(stale)
                    return identity in data["entries"]
            finally:
                if not source_closed:
                    os.close(source_fd)
                    source_closed = True
        except Exception as exc:
            _notice("store", exc)
            return False

    def _enforce_bounds(self, data: dict, now: float, deferred: list | None = None) -> None:
        entries = data["entries"]
        for identity in [
            key
            for key, entry in entries.items()
            if not isinstance(entry, dict)
            or now - float(entry.get("stored_at") or 0) > self.ttl_seconds
        ]:
            self._evict(data, identity, deferred)

        def _unique_total() -> int:
            # Content addressing dedupes: usage counts each object ONCE, and
            # by the VERIFIED on-disk st_size — index claims are untrusted.
            seen: dict[tuple[str, str], int] = {}
            for entry in entries.values():
                if not isinstance(entry, dict):
                    continue
                digest = str(entry.get("digest"))
                suffix = str(entry.get("suffix"))
                if (digest, suffix) in seen:
                    continue
                obj = self._object_path(digest, suffix)
                measured = 0
                if obj is not None:
                    try:
                        info = obj.lstat()
                        if stat.S_ISREG(info.st_mode):
                            measured = info.st_size
                    except OSError:
                        measured = 0
                seen[(digest, suffix)] = measured
            return sum(seen.values())

        while entries and _unique_total() > self.max_total_bytes:
            oldest = min(entries, key=lambda key: float(entries[key].get("last_used") or 0))
            self._evict(data, oldest, deferred)

        # Orphan sweep: objects with no index row, plus stale interrupted
        # incoming files (crashes between creation and finally).
        live = {
            f"{entry.get('digest')}{entry.get('suffix')}"
            for entry in entries.values()
            if isinstance(entry, dict)
        }
        objects = self.root / OBJECTS_DIR
        try:
            for candidate in objects.iterdir():
                if candidate.is_symlink():
                    self._delete(candidate)  # never legitimate here
                    continue
                if candidate.name.startswith(".incoming."):
                    try:
                        if now - candidate.lstat().st_mtime > INCOMING_STALE_SECONDS:
                            candidate.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                if candidate.name not in live:
                    if deferred is not None:
                        deferred.append(candidate)
                    else:
                        self._delete(candidate)
        except OSError:
            pass

    def inspect(self) -> dict:
        try:
            self._validate_tree()
            data = self._read_index()
        except Exception:
            data = {"entries": {}}
        entries = data.get("entries") or {}
        unique: dict[tuple[str, str], int] = {}
        for e in entries.values():
            if isinstance(e, dict):
                unique[(str(e.get("digest")), str(e.get("suffix")))] = int(e.get("size") or 0)
        return {
            "schema_version": CACHE_SCHEMA,
            # Incomplete-feature gate (CONTRACTS.md): the cache is an
            # experimental, non-default capability until its gates pass and
            # the marker's removal is separately reviewed.
            "experimental": True,
            "root": str(self.root),
            "enabled": cache_enabled(read_env_file() if callable(read_env_file) else None),
            "entry_count": len(entries),
            "total_bytes": sum(unique.values()),
            "max_total_bytes": self.max_total_bytes,
            "max_entry_bytes": self.max_entry_bytes,
            "ttl_seconds": self.ttl_seconds,
            "entries": [
                {
                    "source_url": e.get("source_url"),
                    "size": e.get("size"),
                    "stored_at": e.get("stored_at"),
                    "last_used": e.get("last_used"),
                }
                for e in entries.values()
                if isinstance(e, dict)
            ],
        }

    def purge(self) -> bool:
        """Clear the index and every object UNDER THE SAME LOCK the writers
        use (a purge racing an insert must serialize, not shred the root out
        from under it). The root and lock file stay in place; validation is
        the same non-creating check as every other entry point."""
        try:
            self._validate_tree()
            if not self.root.exists():
                return False
            removed = False
            with self._locked():
                index = self._index_path()
                if index.exists():
                    index.unlink(missing_ok=True)
                    removed = True
                objects = self.root / OBJECTS_DIR
                if objects.is_dir():
                    for candidate in objects.iterdir():
                        self._delete(candidate)
                        removed = True
            return removed
        except (CacheUnavailable, OSError):
            return False


if __name__ == "__main__":
    if "--purge" in sys.argv:
        print(json.dumps({"purged": VideoCache().purge()}))
    else:
        print(json.dumps(VideoCache().inspect(), indent=2, sort_keys=True))
