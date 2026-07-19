"""Guards absorbed from the fork scan (2026-07-19).

WATCH_MAX_FILESIZE (credit: aidenlim-dev/AIOFFICE-VideoPro) caps media
downloads via yt-dlp --max-filesize; caption/metadata fetches stay unguarded.
WATCH_DOWNLOAD_CONSENT=required (credit: EmilyYoung71415) refuses to download
media for an uncaptioned URL until the agent confirms with --allow-download.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "watch" / "scripts"))

import acquisition  # noqa: E402
import watch  # noqa: E402


# --- WATCH_MAX_FILESIZE ----------------------------------------------------

@pytest.mark.parametrize("value", ["500M", "1.5G", "750K", "123", "2g"])
def test_max_filesize_accepts_ytdlp_forms(value):
    assert acquisition.validate_max_filesize(value) == value


@pytest.mark.parametrize("value", ["5 GB", "-1M", "abc", "10;rm -rf", "M", ""])
def test_max_filesize_rejects_garbage(value):
    with pytest.raises(ValueError):
        acquisition.validate_max_filesize(value)


def test_max_filesize_none_passthrough():
    assert acquisition.validate_max_filesize(None) is None


def _cmd(**kw):
    defaults = dict(audio_only=False, captions_only=False, languages=("en",),
                    cookie_spec=None)
    defaults.update(kw)
    return acquisition.build_yt_dlp_command("https://x/v", "/tmp/video.%(ext)s", **defaults)


def test_media_command_carries_max_filesize():
    cmd = _cmd(max_filesize="500M")
    i = cmd.index("--max-filesize")
    assert cmd[i + 1] == "500M"


def test_captions_only_command_never_guarded():
    cmd = _cmd(captions_only=True, max_filesize="500M")
    assert "--max-filesize" not in cmd


def test_acquisition_config_reads_max_filesize(monkeypatch):
    monkeypatch.setenv("WATCH_MAX_FILESIZE", "250M")
    cfg = acquisition.acquisition_config({})
    assert cfg["max_filesize"] == "250M"


# --- WATCH_DOWNLOAD_CONSENT ------------------------------------------------

def _blocked(consent, monkeypatch, *, url=True, captions=False, allow=False):
    if consent is None:
        monkeypatch.delenv("WATCH_DOWNLOAD_CONSENT", raising=False)
    else:
        monkeypatch.setenv("WATCH_DOWNLOAD_CONSENT", consent)
    return watch.download_consent_blocked(
        url_source=url, has_captions=captions, allow_flag=allow)


def test_consent_default_off(monkeypatch):
    assert not _blocked(None, monkeypatch)


def test_consent_required_blocks_uncaptioned_url(monkeypatch):
    assert _blocked("required", monkeypatch)


def test_consent_never_blocks_captioned_or_local_or_confirmed(monkeypatch):
    assert not _blocked("required", monkeypatch, captions=True)
    assert not _blocked("required", monkeypatch, url=False)
    assert not _blocked("required", monkeypatch, allow=True)


def test_max_filesize_skip_classified_and_explained():
    fc = acquisition.classify_failure(
        "[download] File is larger than max-filesize (5000 bytes > 1000 bytes)", 0)
    assert fc == acquisition.FailureClass.MAX_FILESIZE_EXCEEDED
    result = acquisition.AcquisitionResult(
        state="fatal", media_path=None, subtitle_candidates=[], selected_subtitle=None,
        metadata={}, source_identity="0" * 64, attempts=[],
        failure_class=acquisition.FailureClass.MAX_FILESIZE_EXCEEDED.value)
    err = acquisition.AcquisitionError(result)
    assert "WATCH_MAX_FILESIZE" in str(err)
