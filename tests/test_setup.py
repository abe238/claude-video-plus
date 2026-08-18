"""setup.py --json surfaces the resolved watch detail and local STT readiness."""
from __future__ import annotations

import json
import os
import platform
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parent.parent / "skills" / "watch" / "scripts" / "setup.py"

# A port nothing listens on, so a loopback STT server on the developer's own
# machine cannot leak into tests that assume no local backend.
DEAD_STT_URL = "http://127.0.0.1:1"


def _run(args, *, home=None, extra_env=None):
    env = dict(os.environ)
    env.pop("WATCH_DETAIL", None)
    # Don't let a real key in the developer's shell env leak into the test.
    env.pop("GROQ_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("SETUP_COMPLETE", None)
    # Nor a real yap install / real :8082 server. Tests that want a local
    # backend opt in explicitly via extra_env.
    # A stale host yt-dlp must not break the silence contract in unrelated
    # tests; staleness tests opt in via extra_env.
    env.setdefault("WATCH_YTDLP_STALE_DAYS", "100000")
    env.setdefault("WATCH_YAP_PATH", "/nonexistent/yap")
    env.setdefault("WATCH_STT_URL", DEAD_STT_URL)
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)  # Windows
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SETUP), *args],
        capture_output=True, text=True, env=env,
    )


def _write_env(home: Path, body: str) -> None:
    cfg = home / ".config" / "watch"
    cfg.mkdir(parents=True, exist_ok=True)
    f = cfg / ".env"
    f.write_text(body, encoding="utf-8")
    f.chmod(0o600)


def test_json_reports_watch_detail():
    proc = _run(["--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["watch_detail"] == "balanced"


def test_keyless_completed_setup_proceeds_silently(tmp_path):
    """A user who finished setup without a key must NOT be nagged forever."""
    _write_env(tmp_path, "GROQ_API_KEY=\nOPENAI_API_KEY=\nSETUP_COMPLETE=true\n")
    chk = _run(["--check"], home=tmp_path)
    assert chk.returncode == 0, f"keyless-complete should pass --check; got {chk.returncode}: {chk.stderr}"
    assert chk.stdout == "" and chk.stderr == ""

    js = json.loads(_run(["--json"], home=tmp_path).stdout)
    assert js["can_proceed"] is True
    assert js["first_run"] is False
    assert js["setup_complete"] is True
    # status still encourages a key even though we can proceed
    assert js["status"] == "needs_key"


def test_keyless_first_run_is_encouraged(tmp_path):
    """Genuine first run with no key: --check reports exit 3 (encourage a key)."""
    _write_env(tmp_path, "GROQ_API_KEY=\nOPENAI_API_KEY=\n")
    chk = _run(["--check"], home=tmp_path)
    assert chk.returncode == 3, chk.stderr

    js = json.loads(_run(["--json"], home=tmp_path).stdout)
    assert js["can_proceed"] is False
    assert js["first_run"] is True


def test_key_present_is_ready(tmp_path):
    _write_env(tmp_path, "GROQ_API_KEY=sk-test-abc\n")
    chk = _run(["--check"], home=tmp_path)
    # A key with no SETUP_COMPLETE is exactly the state v1.4.1 fixed: runnable,
    # but the one-time first-run wizard never ran. It used to exit 0, which made
    # the slimmed Step 0 skip the preference question forever. Exit 5 says
    # "usable, still owes the wizard".
    assert chk.returncode == 5, chk.stderr

    js = json.loads(_run(["--json"], home=tmp_path).stdout)
    assert js["status"] == "ready"
    assert js["can_proceed"] is True
    assert js["whisper_backend"] == "groq"

    # ...and once the wizard has run, --check goes silent for good.
    _write_env(tmp_path, "GROQ_API_KEY=sk-test-abc\nSETUP_COMPLETE=true\n")
    done = _run(["--check"], home=tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "" and done.stderr == ""


# --- local-first readiness ----------------------------------------------------
# The runtime chain is local-http -> yap -> groq -> openai, and cloud Adapters
# refuse without explicit remote authorization. So a reachable local backend
# fully satisfies transcription, and setup must not nag for a cloud key.


def test_local_http_backend_satisfies_setup(tmp_path):
    """A reachable loopback STT server means transcription is covered."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    # Drain probes, or the unaccepted backlog fills and later connects are
    # refused — the second setup.py call would then see no local backend.
    stop = threading.Event()

    def _drain():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except OSError:
                continue

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    try:
        _write_env(tmp_path, "GROQ_API_KEY=\nOPENAI_API_KEY=\n")  # first run, no key
        env = {"WATCH_STT_URL": f"http://127.0.0.1:{port}"}
        chk = _run(["--check"], home=tmp_path, extra_env=env)
        # 0 or 5 both mean "can run": v1.4.1 split out exit 5 for "runnable but
        # the one-time first-run wizard never completed". The subject here is
        # backend detection, not wizard state.
        assert chk.returncode in (0, 5), f"local server should satisfy setup: {chk.stderr}"

        js = json.loads(_run(["--json"], home=tmp_path, extra_env=env).stdout)
        assert js["status"] == "ready"
        assert js["can_proceed"] is True
        assert "local-http" in js["local_stt"]
    finally:
        stop.set()
        t.join(timeout=2)
        srv.close()


@pytest.mark.skipif(platform.system() != "Darwin", reason="yap is macOS-only")
def test_yap_on_path_satisfies_setup(tmp_path):
    """YAP present means transcription is covered without any cloud key."""
    yap = tmp_path / "yap"
    yap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yap.chmod(yap.stat().st_mode | stat.S_IXUSR)

    _write_env(tmp_path, "GROQ_API_KEY=\nOPENAI_API_KEY=\n")  # first run, no key
    env = {"WATCH_YAP_PATH": str(yap)}
    chk = _run(["--check"], home=tmp_path, extra_env=env)
    assert chk.returncode in (0, 5), f"yap should satisfy setup: {chk.stderr}"

    js = json.loads(_run(["--json"], home=tmp_path, extra_env=env).stdout)
    assert js["status"] == "ready"
    assert js["can_proceed"] is True
    assert "yap" in js["local_stt"]


def test_no_backend_reports_empty_local_stt(tmp_path):
    _write_env(tmp_path, "GROQ_API_KEY=\nOPENAI_API_KEY=\n")
    js = json.loads(_run(["--json"], home=tmp_path).stdout)
    assert js["local_stt"] == []


def test_first_run_message_leads_with_local_not_cloud(tmp_path):
    """The old installer demanded a cloud key that is inert without
    --allow-remote-transcription, and never mentioned yap or the loopback
    server. The guidance must name the local options first."""
    proc = _run([], home=tmp_path)  # full installer, no key, no local backend
    out = (proc.stdout + proc.stderr).lower()
    assert "yap" in out, "installer must mention the local YAP backend"
    assert "127.0.0.1:8082" in out or "local" in out
    assert "allow-remote-transcription" in out, (
        "if the installer mentions a cloud key it must say the key alone is "
        "inert without explicit remote authorization"
    )


def test_check_signals_incomplete_first_run_with_exit_5(monkeypatch):
    """can_proceed can be true while SETUP_COMPLETE is false (binaries present,
    a backend configured by hand). That returned 0, and since the slimmed Step 0
    only calls --check, the first-run preference was never asked."""
    import setup as setup_mod
    monkeypatch.setattr(setup_mod, "_status", lambda: {
        "can_proceed": True, "setup_complete": False, "missing_binaries": [],
        "has_api_key": True, "local_stt": [],
    })
    assert setup_mod.cmd_check() == 5


def test_check_stays_silent_when_setup_is_complete(monkeypatch):
    import setup as setup_mod
    monkeypatch.setattr(setup_mod, "_status", lambda: {
        "can_proceed": True, "setup_complete": True, "missing_binaries": [],
        "has_api_key": True, "local_stt": [],
    })
    assert setup_mod.cmd_check() == 0


# --- v1.5.2: yt-dlp staleness warning (prior art: fire17) --------------------

def test_ytdlp_age_parses_the_dated_version(monkeypatch):
    import setup as setup_mod
    class Out:
        returncode = 0
        stdout = "2026.05.01\n"
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: Out())
    age = setup_mod._ytdlp_age_days()
    expected = (setup_mod.datetime.date.today() - setup_mod.datetime.date(2026, 5, 1)).days
    assert age == expected


def test_ytdlp_age_is_none_when_unparseable(monkeypatch):
    import setup as setup_mod
    class Out:
        returncode = 0
        stdout = "not-a-date\n"
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: Out())
    assert setup_mod._ytdlp_age_days() is None


def test_stale_ytdlp_warns_on_check_but_still_exits_zero(tmp_path):
    """Positive control: with the threshold forced to 0 days, any real yt-dlp
    is 'stale' — the warning must appear AND the exit stay 0 (warn-only)."""
    _write_env(tmp_path, "GROQ_API_KEY=sk-test-abc\nSETUP_COMPLETE=true\n")
    chk = _run(["--check"], home=tmp_path, extra_env={"WATCH_YTDLP_STALE_DAYS": "0"})
    assert chk.returncode == 0, chk.stderr
    assert "days old" in chk.stderr and "yt-dlp" in chk.stderr


def test_fresh_ytdlp_keeps_check_silent(tmp_path):
    """Negative control: with a huge threshold, --check is byte-silent."""
    _write_env(tmp_path, "GROQ_API_KEY=sk-test-abc\nSETUP_COMPLETE=true\n")
    chk = _run(["--check"], home=tmp_path, extra_env={"WATCH_YTDLP_STALE_DAYS": "100000"})
    assert chk.returncode == 0, chk.stderr
    assert chk.stdout == "" and chk.stderr == ""


def test_json_reports_staleness_fields(tmp_path):
    js = json.loads(_run(["--json"], home=tmp_path,
                         extra_env={"WATCH_YTDLP_STALE_DAYS": "0"}).stdout)
    assert "ytdlp_age_days" in js and "ytdlp_stale" in js
    if js["ytdlp_age_days"] is not None:
        assert js["ytdlp_stale"] is True  # threshold 0 → any age is stale


# --- v1.5.2: YouTube JS-runtime surfacing (prior art: jryyangjy; severity
# corrected against a both-ways probe — deprecation warning, NOT a 403) -------

def test_js_runtime_detected_when_present(monkeypatch):
    import setup as setup_mod
    monkeypatch.setattr(setup_mod, "_which", lambda n: "/x/" + n if n == "deno" else None)
    assert setup_mod._youtube_js_runtime() == "deno"


def test_js_runtime_none_when_absent(monkeypatch):
    import setup as setup_mod
    monkeypatch.setattr(setup_mod, "_which", lambda n: None)
    assert setup_mod._youtube_js_runtime() is None


def test_json_reports_js_runtime_field(tmp_path):
    js = json.loads(_run(["--json"], home=tmp_path).stdout)
    assert "youtube_js_runtime" in js


def test_missing_runtime_never_blocks_check(tmp_path, monkeypatch):
    """The deprecation is futureproofing, not breakage: --check must stay
    exit 0 and silent even with no JS runtime anywhere."""
    import setup as setup_mod
    _write_env(tmp_path, "GROQ_API_KEY=sk-test-abc\nSETUP_COMPLETE=true\n")
    chk = _run(["--check"], home=tmp_path)
    assert chk.returncode == 0
    assert "runtime" not in (chk.stderr or "")
