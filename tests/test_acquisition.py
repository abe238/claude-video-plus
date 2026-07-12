"""Deterministic acquisition contract and download integration tests (no network)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import acquisition  # noqa: E402
import download  # noqa: E402


URL = "https://www.youtube.com/watch?v=abc123&token=secret"


def completed(cmd: list[str], *, code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, code, stdout="", stderr=stderr)


def acquire(tmp_path: Path, runner, **kwargs) -> acquisition.AcquisitionResult:
    return acquisition.acquire_url(
        URL,
        tmp_path,
        runner=runner,
        pick_media=download._pick_video,
        pick_subtitles=download._subtitle_candidates,
        read_metadata=download._read_info,
        **kwargs,
    )


def test_default_success_is_first_and_does_not_retry(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(list(cmd))
        (tmp_path / "video.mp4").write_bytes(b"media")
        (tmp_path / "video.info.json").write_text(
            json.dumps({"title": "demo", "webpage_url": URL}), encoding="utf-8"
        )
        return completed(cmd)

    result = acquire(tmp_path, runner)

    assert len(calls) == 1
    assert "--extractor-args" not in calls[0]
    assert calls[0][calls[0].index("-f") + 1] == "bv*[height<=720]+ba/b[height<=720]/bv+ba/b"
    assert result.state == "success"
    assert result.selected_strategy == "default"
    assert result.metadata["url"] == "https://www.youtube.com/watch"
    assert result.attempts[0].outcome == "success"


def test_eligible_retry_ladder_is_bounded_and_itag18_is_last(tmp_path: Path):
    calls: list[list[str]] = []
    failures = [
        "YouTube SABR streaming data is missing",
        "HTTP Error 403: Forbidden",
        "requested format is not available",
    ]

    def runner(cmd, **_kwargs):
        calls.append(list(cmd))
        if len(calls) <= len(failures):
            return completed(cmd, code=1, stderr=failures[len(calls) - 1])
        (tmp_path / "video.mp4").write_bytes(b"media")
        return completed(cmd)

    result = acquire(tmp_path, runner)

    assert [attempt.strategy for attempt in result.attempts] == [
        "default",
        "youtube-client:tv",
        "youtube-client:mweb",
        "youtube-format-final:18",
    ]
    assert "youtube:player_client=tv" in calls[1]
    assert "youtube:player_client=mweb" in calls[2]
    assert calls[-1][calls[-1].index("-f") + 1].endswith("/18")
    assert all(
        not call[call.index("-f") + 1].endswith("/18") for call in calls[:-1]
    )
    assert result.state == "degraded"
    assert result.fallback_reason == acquisition.FailureClass.SABR_CLIENT.value


def test_noneligible_failure_never_retries(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(list(cmd))
        return completed(cmd, code=1, stderr="This is a private video; login required")

    result = acquire(tmp_path, runner)

    assert len(calls) == 1
    assert result.state == "fatal"
    assert result.failure_class == acquisition.FailureClass.LOGIN_REQUIRED.value


@pytest.mark.parametrize(
    "value",
    ["unknown", "chrome:/private/profile", "firefox:../profile", "safari:", "chrome:bad\nprofile"],
)
def test_cookie_browser_rejects_unsafe_or_unsupported_profiles(value: str):
    with pytest.raises(ValueError):
        acquisition.validate_cookie_browser(value)


def test_cookie_browser_is_explicit_and_attempt_details_are_redacted(tmp_path: Path):
    cookie = acquisition.validate_cookie_browser("Chrome:Profile 1")
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(list(cmd))
        return completed(
            cmd,
            code=1,
            stderr=f"HTTP Error 403 Authorization: Bearer-private profile={cookie} url={URL}",
        )

    result = acquire(tmp_path, runner, cookie_spec=cookie, player_clients=())

    assert cookie == "chrome:Profile 1"
    assert calls[0][calls[0].index("--cookies-from-browser") + 1] == cookie
    serialized = json.dumps(result.as_dict())
    assert "Profile 1" not in serialized
    assert "Bearer-private" not in serialized
    assert "token=secret" not in serialized
    assert "<redacted>" in serialized


def test_language_order_controls_yt_dlp_and_subtitle_selection(tmp_path: Path):
    languages = acquisition.validate_languages("fr-CA,en")
    for name in ("video.en.vtt", "video.fr.vtt", "video.fr-CA.vtt"):
        (tmp_path / name).write_text("WEBVTT\n", encoding="utf-8")

    ordered = download._subtitle_candidates(tmp_path, languages)
    cmd = acquisition.build_yt_dlp_command(
        URL,
        str(tmp_path / "video.%(ext)s"),
        audio_only=False,
        captions_only=True,
        languages=languages,
        cookie_spec=None,
    )

    assert [path.name for path in ordered] == [
        "video.fr-CA.vtt", "video.fr.vtt", "video.en.vtt"
    ]
    assert cmd[cmd.index("--sub-langs") + 1] == "fr-ca.*,fr,en.*"


def test_http429_caption_exhaustion_uses_json3_without_media_redownload(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(list(cmd))
        sub_format = cmd[cmd.index("--sub-format") + 1]
        if sub_format == "json3":
            # yt-dlp --convert-subs vtt produces the VTT consumed by the pipeline.
            (tmp_path / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
            return completed(cmd)
        return completed(cmd, code=1, stderr="HTTP Error 429: Too Many Requests")

    result = acquire(tmp_path, runner, captions_only=True)

    assert [attempt.strategy for attempt in result.attempts] == [
        "default", "youtube-client:tv", "youtube-client:mweb",
        "captions-json3-after-429",
    ]
    assert calls[-1][calls[-1].index("--sub-format") + 1] == "json3"
    assert all("-f" not in call for call in calls)
    assert result.state == "degraded"
    assert result.selected_subtitle and result.selected_subtitle.endswith("video.en.vtt")


def test_download_local_returns_normalized_and_legacy_fields(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"same bytes, same identity")

    result = download.resolve_local(str(media))

    assert result["state"] == "success"
    assert result["media_path"] == result["video_path"] == str(media.resolve())
    assert result["subtitle_candidates"] == []
    assert result["selected_strategy"] == "local"
    assert result["attempts"] == [{
        "strategy": "local", "outcome": "success", "failure_class": None,
        "exit_code": 0, "detail": None,
    }]
    assert len(result["source_identity"]) == 64
