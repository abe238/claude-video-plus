"""v1.5.6 setup.py --set-key (donlapidos W007): the one sanctioned key entry,
with every safety property enforced. No real secret is used."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SETUP = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts" / "setup.py"


def _run(args, env_extra, stdin=""):
    import os
    env = dict(os.environ)
    env["HOME"] = env_extra["HOME"]
    return subprocess.run(
        [sys.executable, str(SETUP), *args],
        capture_output=True, text=True, input=stdin, env=env,
    )


def test_key_as_argument_is_refused_and_advises_rotation(tmp_path):
    r = _run(["--set-key", "groq", "sk-supersecretkey1234567890"], {"HOME": str(tmp_path)})
    assert r.returncode == 2
    assert "never pass a key on the command line" in r.stderr
    assert "rotate" in r.stderr
    # Nothing written.
    assert not (tmp_path / ".config" / "watch" / ".env").exists()


def test_non_tty_stdin_is_refused(tmp_path):
    # subprocess pipes stdin → not a TTY → must refuse, never hang.
    r = _run(["--set-key", "openai"], {"HOME": str(tmp_path)}, stdin="sk-frompipe\n")
    assert r.returncode == 2
    assert "interactive terminal" in r.stderr
    assert not (tmp_path / ".config" / "watch" / ".env").exists()


def test_unknown_provider_is_refused(tmp_path):
    r = _run(["--set-key", "azure"], {"HOME": str(tmp_path)})
    assert r.returncode == 2


def test_shape_validation_and_0600_via_direct_call(tmp_path, monkeypatch):
    # Drive cmd_set_key directly to exercise the TTY + getpass path.
    import importlib, os
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, str(SETUP.parent))
    setup = importlib.reload(importlib.import_module("setup"))

    import getpass as _getpass
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True, raising=False)

    # Too short → refused, nothing written.
    monkeypatch.setattr(_getpass, "getpass", lambda prompt="": "short")
    assert setup.cmd_set_key(["--set-key", "groq"]) == 2
    assert not setup.CONFIG_FILE.exists()

    # Valid shape → stored, 0600, value never in stdout.
    monkeypatch.setattr(_getpass, "getpass", lambda prompt="": "gsk_" + "a" * 40)
    import io
    buf = io.StringIO()
    monkeypatch.setattr(setup.sys, "stdout", buf)
    assert setup.cmd_set_key(["--set-key", "groq"]) == 0
    content = setup.CONFIG_FILE.read_text()
    assert "GROQ_API_KEY=gsk_" + "a" * 40 in content
    assert (setup.CONFIG_FILE.stat().st_mode & 0o777) == 0o600
    assert "gsk_" not in buf.getvalue()  # value never echoed


def test_skill_md_relays_the_command_not_a_paste():
    text = (SETUP.parent.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "--set-key" in text
    # The old "paste into your editor" guidance is gone.
    assert "in their own editor" not in text
