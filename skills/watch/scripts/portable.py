#!/usr/bin/env python3
"""Deterministic export, verification, and replay of portable Evidence bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping


BUNDLE_SCHEMA_VERSION = 1
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
DEFAULT_MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_MEDIA_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".m4a",
    ".aac", ".flac", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
}
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|secret|password|token)", re.I)
_SECRET_TEXT = re.compile(
    r"(?:authorization\s*:\s*\S+|(?:api[_-]?key|cookie|password|secret)\s*[=:]\s*\S+)",
    re.I,
)


class BundleRefused(ValueError):
    """The requested bundle is unsafe, incomplete, or unverifiable."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_relative(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise BundleRefused("bundle paths must be non-empty POSIX relative paths")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if path.is_absolute() or windows.is_absolute() or windows.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleRefused(f"unsafe bundle path: {value!r}")
    normalized = path.as_posix()
    if normalized == "bundle.json":
        raise BundleRefused("bundle.json is reserved for the bundle manifest")
    return normalized


def _scan_value(value: Any, *, location: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BundleRefused(f"{location} keys must be strings")
            if _SECRET_KEY.search(key):
                raise BundleRefused(f"{location} contains a secret-like field")
            _scan_value(item, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_value(item, location=f"{location}[{index}]")
    elif isinstance(value, str):
        if "\x00" in value or _SECRET_TEXT.search(value):
            raise BundleRefused(f"{location} contains secret-like text")
        if Path(value).expanduser().is_absolute() or PureWindowsPath(value).is_absolute():
            raise BundleRefused(f"{location} contains an absolute private path")
        if value.startswith(("~/", "file://")):
            raise BundleRefused(f"{location} contains an absolute private path")
        if "://" in value and ("?" in value or "#" in value):
            raise BundleRefused(f"{location} contains a signed or non-canonical URL")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise BundleRefused(f"{location} is not JSON-serializable")


def _scan_text_payload(path: str, content: bytes) -> None:
    if PurePosixPath(path).suffix.lower() in _MEDIA_SUFFIXES:
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise BundleRefused(f"non-media artifact is not UTF-8: {path}")
    if _SECRET_TEXT.search(text):
        raise BundleRefused(f"artifact contains secret-like text: {path}")
    try:
        structured = json.loads(text)
    except json.JSONDecodeError:
        structured = None
    if structured is not None:
        _scan_value(structured, location=path)
    absolute_tokens = re.findall(r"(?:^|[\s\"'=])(/[^\s\"']+|~/[^\s\"']+|[A-Za-z]:\\[^\s\"']+)",
                                 text, flags=re.MULTILINE)
    if absolute_tokens:
        raise BundleRefused(f"artifact contains an absolute private path: {path}")
    if re.search(r"https?://[^\s\"']+[?#][^\s\"']+", text):
        raise BundleRefused(f"artifact contains a signed or non-canonical URL: {path}")


def _read_source(source: Path | str | bytes) -> bytes:
    if isinstance(source, bytes):
        return source
    path = Path(source)
    try:
        info = path.lstat()
    except OSError as exc:
        raise BundleRefused(f"cannot read selected artifact {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BundleRefused(f"selected artifact must be a regular non-symlink file: {path}")
    return path.read_bytes()


def _looks_like_media(content: bytes) -> bool:
    return (
        content.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"ID3"))
        or (len(content) >= 12 and content[4:8] == b"ftyp")
        or (content.startswith(b"RIFF") and content[8:12] in {b"WAVE", b"AVI "})
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def _validate_manifest(manifest: Any) -> None:
    required = {
        "bundle_schema_version", "tool_versions", "schema_versions", "evidence_budget",
        "completeness_state", "provenance", "media_included", "files",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise BundleRefused("bundle manifest fields are incomplete or unknown")
    if manifest["bundle_schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise BundleRefused("bundle schema mismatch")
    if not isinstance(manifest["tool_versions"], dict) or not manifest["tool_versions"]:
        raise BundleRefused("bundle tool versions are missing")
    if not isinstance(manifest["schema_versions"], dict) or not manifest["schema_versions"]:
        raise BundleRefused("bundle schema versions are missing")
    if not isinstance(manifest["evidence_budget"], dict):
        raise BundleRefused("bundle Evidence budget is malformed")
    if manifest["completeness_state"] not in {"complete", "partial", "degraded"}:
        raise BundleRefused("bundle completeness state is invalid")
    if not isinstance(manifest["provenance"], dict) or not manifest["provenance"]:
        raise BundleRefused("bundle provenance is missing")
    if not isinstance(manifest["media_included"], bool):
        raise BundleRefused("bundle media declaration is malformed")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise BundleRefused("bundle manifest has no files")


def export_bundle(
    artifacts: Mapping[str, Path | str | bytes],
    output: Path | str,
    *,
    tool_versions: Mapping[str, str],
    schema_versions: Mapping[str, int],
    evidence_budget: Mapping[str, Any],
    completeness_state: str,
    provenance: Mapping[str, Any],
    include_media: bool = False,
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> dict[str, Any]:
    """Export only explicitly selected artifacts to an atomic deterministic ZIP.

    Mapping keys are their desired bundle-relative paths. Source paths are never recorded.
    Media requires an explicit ``include_media=True`` decision.
    """
    if not artifacts:
        raise BundleRefused("at least one artifact must be explicitly selected")
    if max_bundle_bytes <= 0:
        raise ValueError("max_bundle_bytes must be positive")
    if completeness_state not in {"complete", "partial", "degraded"}:
        raise BundleRefused("invalid completeness_state")
    normalized: dict[str, bytes] = {}
    for requested, source in artifacts.items():
        name = _safe_relative(requested)
        if name in normalized:
            raise BundleRefused(f"duplicate artifact path: {name}")
        if PurePosixPath(name).suffix.lower() in _MEDIA_SUFFIXES and not include_media:
            raise BundleRefused(f"media export requires include_media=True: {name}")
        content = _read_source(source)
        if _looks_like_media(content) and not include_media:
            raise BundleRefused(f"media export requires include_media=True: {name}")
        _scan_text_payload(name, content)
        normalized[name] = content
    metadata = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "tool_versions": dict(tool_versions),
        "schema_versions": dict(schema_versions),
        "evidence_budget": dict(evidence_budget),
        "completeness_state": completeness_state,
        "provenance": dict(provenance),
        "media_included": any(PurePosixPath(name).suffix.lower() in _MEDIA_SUFFIXES for name in normalized),
        "files": [
            {"path": name, "bytes": len(normalized[name]),
             "sha256": hashlib.sha256(normalized[name]).hexdigest()}
            for name in sorted(normalized)
        ],
    }
    _validate_manifest(metadata)
    _scan_value(metadata)
    manifest = _canonical_json(metadata)
    projected = len(manifest) + sum(len(value) for value in normalized.values())
    if projected > max_bundle_bytes:
        raise BundleRefused("selected artifacts exceed the portable bundle size bound")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp",
                                           dir=output_path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(_zip_info("bundle.json"), manifest)
            for name in sorted(normalized):
                archive.writestr(_zip_info(name), normalized[name])
        if temporary.stat().st_size > max_bundle_bytes:
            raise BundleRefused("portable bundle exceeds the size bound")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        os.chmod(output_path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(output_path), "bytes": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "files": [item["path"] for item in metadata["files"]],
        "media_included": metadata["media_included"],
    }


def _verified_contents(
    bundle: Path | str,
    *,
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    path = Path(bundle)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bundle_bytes:
            raise BundleRefused("bundle must be a bounded regular non-symlink file")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or "bundle.json" not in names:
                raise BundleRefused("bundle has duplicate paths or no manifest")
            total = 0
            for info in infos:
                if info.is_dir() or info.filename.endswith("/"):
                    raise BundleRefused("bundle directory entries are not allowed")
                if info.filename != "bundle.json":
                    _safe_relative(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise BundleRefused("bundle symlink entries are not allowed")
                total += info.file_size
                if total > max_bundle_bytes:
                    raise BundleRefused("expanded bundle exceeds the size bound")
            try:
                manifest = json.loads(archive.read("bundle.json"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BundleRefused("bundle manifest is invalid") from exc
            _scan_value(manifest)
            _validate_manifest(manifest)
            file_rows = manifest.get("files")
            declared: dict[str, dict[str, Any]] = {}
            for row in file_rows:
                if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
                    raise BundleRefused("bundle file receipt is malformed")
                name = _safe_relative(row["path"])
                if name in declared:
                    raise BundleRefused("bundle manifest repeats a file")
                declared[name] = row
            if set(names) != {"bundle.json", *declared}:
                raise BundleRefused("bundle inventory does not match its manifest")
            contents: dict[str, bytes] = {}
            for name, row in declared.items():
                content = archive.read(name)
                if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                    raise BundleRefused(f"bundle checksum mismatch: {name}")
                if PurePosixPath(name).suffix.lower() in _MEDIA_SUFFIXES and not manifest.get("media_included"):
                    raise BundleRefused("bundle contains undeclared media")
                _scan_text_payload(name, content)
                contents[name] = content
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        if isinstance(exc, BundleRefused):
            raise
        raise BundleRefused(f"cannot verify bundle: {exc}") from exc
    return manifest, contents


def verify_bundle(bundle: Path | str, *, max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES) -> dict[str, Any]:
    manifest, contents = _verified_contents(bundle, max_bundle_bytes=max_bundle_bytes)
    path = Path(bundle)
    return {
        "valid": True, "path": str(path), "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "files": sorted(contents), "manifest": manifest,
    }


def replay_bundle(
    bundle: Path | str,
    output_dir: Path | str,
    *,
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> dict[str, Any]:
    """Verify, then atomically materialize the exact reader-ready artifact bytes."""
    manifest, contents = _verified_contents(bundle, max_bundle_bytes=max_bundle_bytes)
    destination = Path(output_dir)
    if destination.exists() or destination.is_symlink():
        raise BundleRefused("replay destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    os.chmod(temporary, 0o700)
    try:
        for name in sorted(contents):
            target = temporary.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(target.parent, 0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(contents[name])
                handle.flush()
                os.fsync(handle.fileno())
        manifest_path = temporary / "bundle.json"
        manifest_path.write_bytes(_canonical_json(manifest))
        os.chmod(manifest_path, 0o600)
        os.replace(temporary, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {
        "path": str(destination), "files": sorted(contents),
        "manifest": str(destination / "bundle.json"),
        "content_sha256": {
            name: hashlib.sha256(contents[name]).hexdigest() for name in sorted(contents)
        },
    }
