from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile

import pytest

from portable import BundleRefused, export_bundle, replay_bundle, verify_bundle


def metadata():
    return {
        "tool_versions": {"watch": "1.0"},
        "schema_versions": {"evidence": 1},
        "evidence_budget": {"max_text_tokens": 8000, "max_images": 24},
        "completeness_state": "complete",
        "provenance": {"source_identity": "a" * 64, "policy": "targeted-v1"},
    }


def export(artifacts, output, **updates):
    options = metadata()
    options.update(updates)
    return export_bundle(artifacts, output, **options)


def test_export_is_deterministic_owner_only_verified_and_replayable(tmp_path):
    artifacts = {
        "evidence/manifest.json": json.dumps(
            {"schema_version": 1, "frame": "frames/one.jpg"}, sort_keys=True
        ).encode(),
        "evidence/report.txt": b"reader-ready evidence\n",
    }
    first = tmp_path / "first.evidence"
    second = tmp_path / "second.evidence"
    one = export(artifacts, first)
    two = export(dict(reversed(list(artifacts.items()))), second)

    assert first.read_bytes() == second.read_bytes()
    assert one["sha256"] == two["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    verified = verify_bundle(first)
    assert verified["valid"] is True
    assert verified["files"] == sorted(artifacts)
    assert verified["manifest"]["evidence_budget"] == metadata()["evidence_budget"]

    replay = replay_bundle(first, tmp_path / "replayed")
    assert replay["files"] == sorted(artifacts)
    for name, content in artifacts.items():
        path = tmp_path / "replayed" / name
        assert path.read_bytes() == content
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads((tmp_path / "replayed" / "bundle.json").read_text()) == verified["manifest"]
    with pytest.raises(BundleRefused, match="must not already exist"):
        replay_bundle(first, tmp_path / "replayed")


@pytest.mark.parametrize("name", ["../secret.txt", "/absolute.txt", "C:\\private.txt", "a\\b.txt"])
def test_export_refuses_traversal_and_absolute_paths(tmp_path, name):
    with pytest.raises(BundleRefused, match="path"):
        export({name: b"safe"}, tmp_path / "bundle.evidence")


def test_export_refuses_symlink_sources(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(BundleRefused, match="non-symlink"):
        export({"evidence/report.txt": link}, tmp_path / "bundle.evidence")


def test_export_refuses_secrets_private_paths_signed_urls_and_default_media(tmp_path):
    with pytest.raises(BundleRefused, match="secret-like"):
        export({"report.txt": b"Authorization: Bearer value"}, tmp_path / "secret.evidence")
    with pytest.raises(BundleRefused, match="absolute private path"):
        export({"manifest.json": b'{"path":"/Users/private/video.mov"}'},
               tmp_path / "path.evidence")
    with pytest.raises(BundleRefused, match="non-canonical URL"):
        export({"manifest.json": b'{"url":"https://example.test/v?id=signed"}'},
               tmp_path / "url.evidence")
    with pytest.raises(BundleRefused, match="secret-like field"):
        export({"report.txt": b"safe"}, tmp_path / "metadata.evidence",
               provenance={"api_key": "value"})
    with pytest.raises(BundleRefused, match="include_media"):
        export({"frames/one.jpg": b"\xff\xd8\xffpayload"}, tmp_path / "media.evidence")
    with pytest.raises(BundleRefused, match="include_media"):
        export({"payload.bin": b"\x89PNG\r\n\x1a\npayload"}, tmp_path / "disguised.evidence")

    receipt = export({"frames/one.jpg": b"\xff\xd8\xffpayload"},
                     tmp_path / "explicit-media.evidence", include_media=True)
    assert receipt["media_included"] is True
    assert verify_bundle(tmp_path / "explicit-media.evidence")["valid"] is True


def test_verify_detects_checksum_changes_missing_files_and_traversal(tmp_path):
    original = tmp_path / "original.evidence"
    export({"report.txt": b"original"}, original)

    changed = tmp_path / "changed.evidence"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(changed, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            target.writestr(info, b"changed" if info.filename == "report.txt" else content)
    with pytest.raises(BundleRefused, match="checksum mismatch"):
        verify_bundle(changed)

    missing = tmp_path / "missing.evidence"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(missing, "w") as target:
        target.writestr("bundle.json", source.read("bundle.json"))
    with pytest.raises(BundleRefused, match="inventory"):
        verify_bundle(missing)

    traversal = tmp_path / "traversal.evidence"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("bundle.json", b"{}")
        archive.writestr("../escape.txt", b"unsafe")
    with pytest.raises(BundleRefused, match="unsafe bundle path"):
        verify_bundle(traversal)


def test_verify_refuses_zip_symlink_entries(tmp_path):
    bundle = tmp_path / "symlink.evidence"
    link = zipfile.ZipInfo("link.txt")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("bundle.json", b"{}")
        archive.writestr(link, b"target.txt")
    with pytest.raises(BundleRefused, match="symlink"):
        verify_bundle(bundle)
