#!/usr/bin/env python3
"""Private, bounded, checksum-verified derived Evidence state.

This module is deliberately not wired into the default watch path. Callers must opt in
to persistence and decide whether transcript/OCR/index data may be retained.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterator


STATE_SCHEMA_VERSION = 1
DEFAULT_ROOT = Path("~/.cache/watch/evidence-v1").expanduser()
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
LOCK_STALE_SECONDS = 30.0
LOCK_WAIT_SECONDS = 5.0
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KINDS = {"transcript", "ocr", "embedding", "scout", "scout_index"}
_MEDIA_KINDS = {"audio", "video", "image", "frame", "frames", "crop", "media", "source_media"}
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|secret|password|access[_-]?token|refresh[_-]?token|bearer[_-]?token)",
    re.I,
)
_SECRET_TEXT = re.compile(
    r"(?:authorization\s*:\s*\S+|(?:api[_-]?key|cookie|password|secret)\s*[=:]\s*\S+)",
    re.I,
)


class StateUnavailable(RuntimeError):
    """The state store cannot be used safely; the caller should continue uncached."""


@dataclass(frozen=True)
class CacheKey:
    """All inputs that can change reusable Evidence output."""

    source_identity: str
    range_start: float | None = None
    range_end: float | None = None
    language: str = "auto"
    adapter: str = "none"
    model: str = "none"
    policy: str = "default"
    schema_version: int = STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _HEX64.fullmatch(self.source_identity):
            raise ValueError("source_identity must be a lowercase SHA-256 digest")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if self.range_start is not None and self.range_start < 0:
            raise ValueError("range_start must be non-negative")
        if self.range_end is not None and self.range_end < 0:
            raise ValueError("range_end must be non-negative")
        if (self.range_start is not None and self.range_end is not None
                and self.range_end <= self.range_start):
            raise ValueError("range_end must be greater than range_start")
        for name in ("language", "adapter", "model", "policy"):
            value = getattr(self, name)
            if not value or "\x00" in value:
                raise ValueError(f"{name} must be a non-empty safe string")
            if (_SECRET_TEXT.search(value) or Path(value).expanduser().is_absolute()
                    or PureWindowsPath(value).is_absolute() or value.startswith(("~/", "file://"))
                    or ("://" in value and ("?" in value or "#" in value))):
                raise ValueError(f"{name} contains secret or private provenance")

    def canonical_bytes(self) -> bytes:
        return _canonical_json(asdict(self))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class StateRead:
    status: str  # hit | miss | disabled
    reason: str
    payload: Any = None
    payload_kind: str | None = None


@dataclass(frozen=True)
class StateWrite:
    stored: bool
    reason: str
    key_digest: str
    bytes: int = 0


@dataclass(frozen=True)
class PurgeResult:
    removed_entries: int
    removed_bytes: int
    remaining_entries: int
    remaining_bytes: int


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _owner_only(path: Path, *, directory: bool) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return False
    if directory and not stat.S_ISDIR(info.st_mode):
        return False
    if not directory and not stat.S_ISREG(info.st_mode):
        return False
    if info.st_mode & 0o077:
        return False
    getuid = getattr(os, "getuid", None)
    return getuid is None or info.st_uid == getuid()


def _safe_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            if _SECRET_KEY.search(key):
                raise ValueError(f"{path} contains a secret-like field")
            if key.lower() in _MEDIA_KINDS and isinstance(item, (str, list, dict)) and item:
                raise ValueError(f"{path} contains persisted media")
            _safe_payload(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _safe_payload(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if "\x00" in value or _SECRET_TEXT.search(value):
            raise ValueError(f"{path} contains secret-like text")
        candidate = Path(value).expanduser()
        if candidate.is_absolute() or value.startswith(("file://", "~/")):
            raise ValueError(f"{path} contains an absolute private path")
        if "://" in value and ("?" in value or "#" in value):
            raise ValueError(f"{path} contains a non-canonical URL")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise TypeError(f"{path} is not JSON-serializable")


class EvidenceState:
    """An atomic JSON state store that fails closed and lets callers fail open."""

    def __init__(
        self,
        root: Path | str = DEFAULT_ROOT,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        allow_sensitive: bool = False,
    ) -> None:
        if ttl_seconds <= 0 or max_bytes <= 0:
            raise ValueError("ttl_seconds and max_bytes must be positive")
        self.root = Path(root).expanduser()
        self.ttl_seconds = int(ttl_seconds)
        self.max_bytes = int(max_bytes)
        self.allow_sensitive = bool(allow_sensitive)

    def _prepare(self) -> None:
        if self.root.exists() or self.root.is_symlink():
            if not _owner_only(self.root, directory=True):
                raise StateUnavailable("unsafe state directory permissions or type")
            return
        try:
            self.root.mkdir(parents=True, mode=0o700)
            os.chmod(self.root, 0o700)
        except FileExistsError:
            # Another writer may create the root between the existence check and mkdir.
            pass
        if not _owner_only(self.root, directory=True):
            raise StateUnavailable("could not create an owner-only state directory")

    def _entry(self, key: CacheKey) -> Path:
        return self.root / f"{key.digest}.json"

    def _entries(self) -> Iterator[Path]:
        if not self.root.is_dir():
            return
        for path in self.root.iterdir():
            if path.name.endswith(".json") and not path.is_symlink():
                yield path

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._prepare()
        lock = self.root / ".write-lock"
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                lock.mkdir(mode=0o700)
                (lock / "owner").write_text(f"{os.getpid()}\n", encoding="ascii")
                os.chmod(lock / "owner", 0o600)
                break
            except FileExistsError:
                try:
                    stale = time.time() - lock.lstat().st_mtime > LOCK_STALE_SECONDS
                except OSError:
                    continue
                if stale and not lock.is_symlink():
                    shutil.rmtree(lock, ignore_errors=True)
                    continue
                if time.monotonic() >= deadline:
                    raise StateUnavailable("timed out waiting for state write lock")
                time.sleep(0.02)
        try:
            yield
        finally:
            shutil.rmtree(lock, ignore_errors=True)

    def get(self, key: CacheKey, *, now: float | None = None) -> StateRead:
        try:
            self._prepare()
        except StateUnavailable as exc:
            return StateRead("disabled", str(exc))
        path = self._entry(key)
        if not path.exists() or path.is_symlink():
            return StateRead("miss", "not_found")
        if not _owner_only(path, directory=False):
            return StateRead("miss", "unsafe_permissions")
        try:
            if path.stat().st_size > self.max_bytes:
                return StateRead("miss", "entry_too_large")
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope.get("state_schema_version") != STATE_SCHEMA_VERSION:
                return StateRead("miss", "schema_mismatch")
            if envelope.get("key") != asdict(key) or envelope.get("key_digest") != key.digest:
                return StateRead("miss", "key_mismatch")
            payload = envelope["payload"]
            observed = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if observed != envelope.get("payload_sha256"):
                return StateRead("miss", "checksum_mismatch")
            current = time.time() if now is None else float(now)
            if current >= float(envelope["expires_at"]):
                return StateRead("miss", "expired")
            _safe_payload(payload)
            return StateRead("hit", "verified", payload, envelope.get("payload_kind"))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return StateRead("miss", "corrupt")

    def put(
        self,
        key: CacheKey,
        payload: Any,
        *,
        payload_kind: str = "receipt",
        now: float | None = None,
    ) -> StateWrite:
        if payload_kind in _MEDIA_KINDS:
            return StateWrite(False, "media_persistence_forbidden", key.digest)
        if payload_kind in _SENSITIVE_KINDS and not self.allow_sensitive:
            return StateWrite(False, "sensitive_persistence_not_enabled", key.digest)
        try:
            _safe_payload(payload)
            created = time.time() if now is None else float(now)
            envelope = {
                "state_schema_version": STATE_SCHEMA_VERSION,
                "key": asdict(key),
                "key_digest": key.digest,
                "created_at": created,
                "expires_at": created + self.ttl_seconds,
                "payload_kind": payload_kind,
                "payload_sha256": hashlib.sha256(_canonical_json(payload)).hexdigest(),
                "payload": payload,
            }
            encoded = _canonical_json(envelope)
            if len(encoded) > self.max_bytes:
                return StateWrite(False, "entry_exceeds_store_bound", key.digest)
            with self._locked():
                self._purge_locked(now=created, reserve_bytes=len(encoded), exclude=self._entry(key))
                current = sum(path.stat().st_size for path in self._entries())
                existing = self._entry(key).stat().st_size if self._entry(key).is_file() else 0
                if current - existing + len(encoded) > self.max_bytes:
                    return StateWrite(False, "store_bound_exhausted", key.digest)
                fd, temporary_name = tempfile.mkstemp(prefix=f".{key.digest}.", suffix=".tmp", dir=self.root)
                temporary = Path(temporary_name)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self._entry(key))
                    os.chmod(self._entry(key), 0o600)
                finally:
                    temporary.unlink(missing_ok=True)
            return StateWrite(True, "stored", key.digest, len(encoded))
        except (OSError, StateUnavailable, TypeError, ValueError) as exc:
            return StateWrite(False, f"disabled:{exc}", key.digest)

    def _purge_locked(self, *, now: float, reserve_bytes: int = 0, exclude: Path | None = None) -> PurgeResult:
        entries: list[tuple[Path, int, float, bool]] = []
        for path in self._entries():
            try:
                size = path.stat().st_size
                expires = 0.0
                try:
                    expires = float(json.loads(path.read_text(encoding="utf-8")).get("expires_at", 0))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
                entries.append((path, size, path.stat().st_mtime, expires <= now))
            except OSError:
                continue
        removed_entries = removed_bytes = 0
        for path, size, _, expired in entries:
            if expired and path != exclude:
                try:
                    path.unlink()
                    removed_entries += 1
                    removed_bytes += size
                except OSError:
                    pass
        survivors = [(path, size, mtime) for path, size, mtime, expired in entries
                     if not expired and path.exists()]
        total = sum(size for _, size, _ in survivors)
        for path, size, _ in sorted(survivors, key=lambda item: (item[2], item[0].name)):
            if total + reserve_bytes <= self.max_bytes:
                break
            if path == exclude:
                continue
            try:
                path.unlink()
                total -= size
                removed_entries += 1
                removed_bytes += size
            except OSError:
                pass
        remaining = list(self._entries())
        return PurgeResult(removed_entries, removed_bytes, len(remaining),
                           sum(path.stat().st_size for path in remaining))

    def purge(self, *, expired_only: bool = False, now: float | None = None) -> PurgeResult:
        current = time.time() if now is None else float(now)
        try:
            with self._locked():
                if expired_only:
                    return self._purge_locked(now=current)
                removed_entries = removed_bytes = 0
                for path in list(self._entries()):
                    try:
                        size = path.stat().st_size
                        path.unlink()
                        removed_entries += 1
                        removed_bytes += size
                    except OSError:
                        pass
                return PurgeResult(removed_entries, removed_bytes, 0, 0)
        except StateUnavailable:
            return PurgeResult(0, 0, 0, 0)

    def verify(self, *, now: float | None = None) -> dict[str, Any]:
        try:
            self._prepare()
        except StateUnavailable as exc:
            return {"usable": False, "reason": str(exc), "entries": []}
        entries = []
        for path in sorted(self._entries()):
            digest = path.stem
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                key = CacheKey(**envelope["key"])
                result = self.get(key, now=now)
                entries.append({"key_digest": digest, "status": result.status, "reason": result.reason,
                                "bytes": path.stat().st_size})
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                entries.append({"key_digest": digest, "status": "miss", "reason": "corrupt",
                                "bytes": path.stat().st_size if path.exists() else 0})
        return {"usable": True, "root": str(self.root), "entries": entries,
                "bytes": sum(item["bytes"] for item in entries)}
