"""Deterministic acquisition contract and download integration tests (no network)."""
from __future__ import annotations

import json
import os
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
    assert calls[0][calls[0].index("-f") + 1] == (
        "bv*[height<=720]+ba/b[height<=720]"
        "/bv*[height<=?720]+ba/b[height<=?720]"
        "/wv*+ba/w"
    )
    assert result.state == "success"
    assert result.selected_strategy == "default"
    assert result.metadata["url"] == "https://www.youtube.com/watch"
    assert result.attempts[0].outcome == "success"


def test_video_format_ladder_is_resolution_bounded(tmp_path: Path):
    # fork-watch (androsland/moviola): the ladder must never fall through to an
    # unbounded best-video tail (which fetches a 4K upload on a size-capped path),
    # and must keep formats that carry NO resolution metadata (<=?720 rungs).
    calls: list[list[str]] = []

    def runner(cmd, **_kw):
        calls.append(list(cmd))
        (tmp_path / "video.mp4").write_bytes(b"m")
        (tmp_path / "video.info.json").write_text(json.dumps({"title": "d"}), encoding="utf-8")
        return completed(cmd)

    acquire(tmp_path, runner)
    fmt = calls[0][calls[0].index("-f") + 1]
    assert "[height<=?720]" in fmt          # unknown-resolution HLS formats kept
    assert "/wv*+ba/w" in fmt               # bounded worst-rendition tail
    assert "/bv+ba/b" not in fmt            # the old UNBOUNDED tail is gone
    # every rung either caps height or is the explicit worst rendition
    for rung in fmt.split("/"):
        assert ("height<=" in rung) or rung.startswith("w"), rung


def test_informative_403_is_not_masked_by_a_noisier_retry(tmp_path: Path):
    # The default strategy 403s (stale yt-dlp); a later forced-format retry emits
    # an unclassifiable error. The aggregate failure_class must stay http_403,
    # not degrade to "unknown". Live-observed regression.
    seen: list[int] = []

    def runner(cmd, **_kwargs):
        seen.append(1)
        if len(seen) == 1:
            return completed(cmd, code=1, stderr="ERROR: unable to download video data: HTTP Error 403: Forbidden")
        return completed(cmd, code=1, stderr="ERROR: something weird happened with no known signature")

    result = acquire(tmp_path, runner)
    assert result.state == "fatal"
    assert len(seen) > 1  # it did retry past the first 403
    assert result.failure_class == acquisition.FailureClass.HTTP_403.value


def test_acquisition_error_403_message_points_at_yt_dlp_upgrade():
    result = acquisition.AcquisitionResult(
        state="fatal", media_path=None, subtitle_candidates=[], selected_subtitle=None,
        metadata={}, source_identity="yt:x", failure_class=acquisition.FailureClass.HTTP_403.value,
    )
    err = acquisition.AcquisitionError(result)
    msg = str(err)
    assert "http_403" in msg
    assert "pip install -U yt-dlp" in msg  # actionable remediation


def _reset_selfheal():
    with acquisition._ytdlp_state_lock:
        acquisition._force_module = False
        acquisition._upgrade_attempted = False
    acquisition._detect_ytdlp_cmd.cache_clear()


def _rc0(cmd, **_kw):
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_ytdlp_autoupdate_enabled_default_and_optout(monkeypatch):
    monkeypatch.delenv("WATCH_YTDLP_AUTOUPDATE", raising=False)
    assert acquisition.ytdlp_autoupdate_enabled({}) is True
    for off in ("0", "false", "No", "off"):
        assert acquisition.ytdlp_autoupdate_enabled({"WATCH_YTDLP_AUTOUPDATE": off}) is False
    assert acquisition.ytdlp_autoupdate_enabled({"WATCH_YTDLP_AUTOUPDATE": "1"}) is True
    # env-over-file: a real environment variable wins over the .env mapping.
    monkeypatch.setenv("WATCH_YTDLP_AUTOUPDATE", "0")
    assert acquisition.ytdlp_autoupdate_enabled({"WATCH_YTDLP_AUTOUPDATE": "1"}) is False


def test_upgrade_ytdlp_success_is_hardened_and_forces_fresh_module(monkeypatch):
    _reset_selfheal()
    # Hostile ambient config that MUST NOT reach the subprocess.
    monkeypatch.setenv("PIP_INDEX_URL", "https://evil.example/simple/")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://evil.example/extra/")
    monkeypatch.setenv("PYTHONPATH", "/hostile")
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    try:
        assert acquisition.upgrade_ytdlp(runner=runner) is True
        install, kw = calls[0]
        # hardened + isolated + fixed argv + official index (no injection surface)
        assert install[0] == sys.executable
        assert "-E" in install                         # PYTHON* env dropped
        assert "--isolated" in install                 # PIP_* env/config ignored
        assert "https://pypi.org/simple/" in install   # official PyPI, not PIP_INDEX_URL
        assert install[-3:] == ["--user", "--upgrade", "yt-dlp"]
        # env is scrubbed: no PIP_*/PYTHONPATH; pip config-file loading disabled.
        env = kw["env"]
        assert not any(k.startswith("PIP_") and k != "PIP_CONFIG_FILE" for k in env)
        assert env["PIP_CONFIG_FILE"] == os.devnull    # global/site pip.conf ignored
        assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
        assert kw["cwd"] == acquisition._SAFE_CWD       # not the caller's CWD
        # it also probed the module before trusting it, then forces the module.
        assert any("yt_dlp" in c and "--version" in c for c, _ in calls)
        forced = acquisition.ytdlp_cmd()
        assert forced[0] == sys.executable and forced[-2:] == ("-m", "yt_dlp")
    finally:
        _reset_selfheal()


def test_upgrade_ytdlp_rc0_but_module_unrunnable_returns_false():
    _reset_selfheal()

    def runner(cmd, **_kw):
        # pip succeeds, but the yt_dlp --version probe fails.
        rc = 1 if ("yt_dlp" in cmd and "--version" in cmd) else 0
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")

    try:
        assert acquisition.upgrade_ytdlp(runner=runner) is False
        assert acquisition._force_module is False  # not trusted
    finally:
        _reset_selfheal()


def test_upgrade_ytdlp_is_latched_once_per_process():
    _reset_selfheal()
    n = {"pip": 0}

    def runner(cmd, **_kw):
        if "pip" in cmd:
            n["pip"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    try:
        assert acquisition.upgrade_ytdlp(runner=runner) is True
        # second call must NOT reinstall; returns the latched outcome.
        assert acquisition.upgrade_ytdlp(runner=runner) is True
        assert n["pip"] == 1
    finally:
        _reset_selfheal()


def test_upgrade_ytdlp_failure_returns_false_and_does_not_force_module():
    _reset_selfheal()

    def raises(cmd, **_kw):
        raise OSError("no pip")

    try:
        assert acquisition.upgrade_ytdlp(runner=raises) is False
        assert acquisition._force_module is False
    finally:
        _reset_selfheal()


def _fatal_403():
    return acquisition.AcquisitionResult(
        state="fatal", media_path=None, subtitle_candidates=[], selected_subtitle=None,
        metadata={}, source_identity="yt:x", failure_class=acquisition.FailureClass.HTTP_403.value,
    )


def test_download_url_self_heals_on_stale_403(tmp_path: Path, monkeypatch):
    import download
    ok = acquisition.AcquisitionResult(
        state="success", media_path=str(tmp_path / "v.mp4"), subtitle_candidates=[],
        selected_subtitle=None, metadata={"url": "https://y/x"}, source_identity="yt:x",
        downloaded=True,
    )
    seq = [_fatal_403(), ok]
    calls = {"acquire": 0, "upgrade": 0}
    monkeypatch.setattr(download, "acquire_url", lambda *a, **k: (calls.__setitem__("acquire", calls["acquire"] + 1) or seq.pop(0)))
    monkeypatch.setattr(download, "upgrade_ytdlp", lambda *a, **k: calls.__setitem__("upgrade", calls["upgrade"] + 1) or True)
    monkeypatch.setattr(download, "read_env_file", lambda: {})
    payload = download.download_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert calls["upgrade"] == 1 and calls["acquire"] == 2
    assert payload["state"] == "success"


def test_download_url_fatal_retry_preserves_original_actionable_error(tmp_path: Path, monkeypatch):
    import download
    # Retry ALSO fatal but with a vaguer class: the original http_403 must be the
    # one raised (its message points at the yt-dlp upgrade).
    retry_fatal = acquisition.AcquisitionResult(
        state="fatal", media_path=None, subtitle_candidates=[], selected_subtitle=None,
        metadata={}, source_identity="yt:x", failure_class=acquisition.FailureClass.UNKNOWN.value,
    )
    seq = [_fatal_403(), retry_fatal]
    monkeypatch.setattr(download, "acquire_url", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(download, "upgrade_ytdlp", lambda *a, **k: True)
    monkeypatch.setattr(download, "read_env_file", lambda: {})
    import pytest as _pytest
    with _pytest.raises(acquisition.AcquisitionError) as exc:
        download.download_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert exc.value.result.failure_class == acquisition.FailureClass.HTTP_403.value


def test_download_url_retry_that_raises_preserves_original_403(tmp_path: Path, monkeypatch):
    import download
    seq = [_fatal_403()]

    def acquire(*_a, **_k):
        if seq:
            return seq.pop(0)
        raise SystemExit("yt-dlp is not usable")  # retry raises instead of returning

    monkeypatch.setattr(download, "acquire_url", acquire)
    monkeypatch.setattr(download, "upgrade_ytdlp", lambda *a, **k: True)
    monkeypatch.setattr(download, "read_env_file", lambda: {})
    import pytest as _pytest
    with _pytest.raises(acquisition.AcquisitionError) as exc:
        download.download_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert exc.value.result.failure_class == acquisition.FailureClass.HTTP_403.value


def test_download_url_optout_via_env_file_skips_selfheal(tmp_path: Path, monkeypatch):
    import download
    calls = {"acquire": 0, "upgrade": 0}
    monkeypatch.setattr(download, "acquire_url", lambda *a, **k: (calls.__setitem__("acquire", calls["acquire"] + 1) or _fatal_403()))
    monkeypatch.setattr(download, "upgrade_ytdlp", lambda *a, **k: calls.__setitem__("upgrade", calls["upgrade"] + 1) or True)
    # opt-out lives in ~/.config/watch/.env (NOT the process env) — the production
    # wiring must read it. Codex blocker 2.
    monkeypatch.delenv("WATCH_YTDLP_AUTOUPDATE", raising=False)
    monkeypatch.setattr(download, "read_env_file", lambda: {"WATCH_YTDLP_AUTOUPDATE": "0"})
    import pytest as _pytest
    with _pytest.raises(acquisition.AcquisitionError):
        download.download_url("https://www.youtube.com/watch?v=x", tmp_path)
    assert calls["upgrade"] == 0 and calls["acquire"] == 1


def test_stale_media_cannot_make_failed_attempt_succeed(tmp_path: Path):
    (tmp_path / "video.mp4").write_bytes(b"stale partial")

    def runner(cmd, **_kwargs):
        return completed(cmd, code=1, stderr="private video; login required")

    result = acquire(tmp_path, runner)
    assert result.state == "fatal"
    assert result.attempts[0].outcome == "failed"
    assert not (tmp_path / "video.mp4").exists()


def test_eligible_retry_ladder_is_bounded_and_itag18_is_last(tmp_path: Path):
    calls: list[list[str]] = []
    failures = [
        "YouTube SABR streaming data is missing",
        "HTTP Error 403: Forbidden",
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
        "youtube-client:android_vr",
        "youtube-client:tv",
        "youtube-client:mweb",
        "youtube-format-final:18",
    ]
    assert "youtube:player_client=android_vr" in calls[1]
    assert "youtube:player_client=tv" in calls[2]
    assert "youtube:player_client=mweb" in calls[3]
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


def test_attempt_details_redact_private_absolute_paths():
    text = "cookies at /Users/alice/Library/Chrome/Cookies and C:\\Users\\alice\\Cookies.db"
    redacted = acquisition.redact_text(text)
    assert "/Users/alice" not in redacted
    assert "C:\\Users\\alice" not in redacted
    assert "<redacted-path>" in redacted


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
    # v1.5.4 (#92/#123): each language gains its `-orig` original track
    # (regional AND base forms), and English's wildcard becomes the explicit
    # set that ever wins selection.
    assert cmd[cmd.index("--sub-langs") + 1] == "fr-CA-orig,fr-orig,fr-CA.*,fr,en-orig,en,en-US,en-GB"


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
        "default", "youtube-client:android_vr", "youtube-client:tv", "youtube-client:mweb",
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


def test_no_exec_is_unconditional_ignore_config_is_scoped(tmp_path):
    from acquisition import build_yt_dlp_command

    for captions_only, audio_only in ((True, False), (False, False), (False, True)):
        # --no-exec: always on (nothing legit needs yt-dlp --exec here).
        for ic in (True, False):
            cmd = build_yt_dlp_command(
                "https://youtu.be/x", str(tmp_path / "video.%(ext)s"),
                audio_only=audio_only, captions_only=captions_only,
                languages=("en",), cookie_spec=None, ignore_config=ic,
            )
            assert "--no-exec" in cmd
            # --ignore-config: only when requested (cache-participating runs).
            assert ("--ignore-config" in cmd) is ic


def test_ignore_config_scope_follows_video_cache_flag(monkeypatch):
    from acquisition import acquisition_config

    monkeypatch.delenv("WATCH_VIDEO_CACHE", raising=False)
    assert acquisition_config({})["ignore_config"] is False       # cache off: respect user config
    assert acquisition_config({"WATCH_VIDEO_CACHE": "1"})["ignore_config"] is True
    monkeypatch.setenv("WATCH_VIDEO_CACHE", "true")
    assert acquisition_config({})["ignore_config"] is True         # cache on: suppress ambient config
