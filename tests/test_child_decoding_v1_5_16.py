"""Child-process output must be decoded as UTF-8, not as the system locale.

`subprocess.run(..., text=True)` with no `encoding=` decodes using the C-level
locale encoding. ffmpeg, yt-dlp, yap and the whisper CLI all emit UTF-8 no
matter what the console locale is, so on a non-UTF-8 multibyte locale
(cp949/eucKR Korean, eucJP Japanese, GB18030 Chinese Windows or terminal) the
decode raises UnicodeDecodeError on the first non-ASCII byte.

REPRODUCED 2026-09-25 before the fix:
    LC_ALL=ko_KR.eucKR python3 -c "subprocess.run(child, text=True)"
    UnicodeDecodeError: 'euc_kr' codec can't decode byte 0xec in position 8

Two shapes of damage, and they need OPPOSITE fixes:

  * DIAGNOSTIC output (ffmpeg/whisper-CLI chatter nobody parses) — the decode
    still happens even when the text is discarded, so it crashes a run over
    output we never wanted. `errors="replace"` is right here.

  * CONTENT output — `YapAdapter._transcribe_one` captures stdout that IS the
    transcript: it is checked for "WEBVTT", written to a .vtt and parsed.
    A blanket `errors="replace"` there would turn today's loud crash into
    U+FFFD mojibake written out as a valid-looking transcript, on every
    non-English video. That is a failure that exits 0, so the content path
    gets `encoding="utf-8"` with NO `errors=` and stays loud.

Upstream and two forks shipped fixes for this theme in tests and console
output only (wooay123-cloud, yangjilife, upstream de8b5b5); none touched the
content path.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import evidence
import setup as setup_mod
import transcription_adapters as adapters
import transcription_chunks as chunks

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "watch" / "scripts"
KOREAN = "오반 강남 스타일"


def _non_utf8_locale() -> str | None:
    """A locale whose codec ACTUALLY fails on UTF-8 bytes, or None.

    Two traps this helper exists to avoid, both found by the Codex review:

    * Name matching is brittle — a whitelist of codec names missed CP949,
      EUC-KR, SJIS, GB2312 and Big5HKSCS across two review rounds, silently
      skipping the reproduction on machines that could run it. So there is no
      whitelist: every non-UTF-8 locale is a candidate.
    * A skip must never look like a pass, so the candidate is VERIFIED: we run
      a child under it and confirm its effective decoder really rejects UTF-8.
      A locale the OS silently coerces back to UTF-8 (PEP 540 does this for
      C/POSIX) is rejected rather than trusted.
    """
    try:
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None

    probe = (
        "import sys,locale\n"
        "enc = locale.getencoding()\n"
        "try:\n"
        "    '오'.encode('utf-8').decode(enc)\n"
        "except (UnicodeDecodeError, LookupError):\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    for name in out.stdout.split():
        # No codec whitelist: Codex round 2 showed SJIS, GB2312 and Big5HKSCS
        # were skipped despite failing on UTF-8. Any locale with a codec that
        # is not UTF-8 is a candidate; the child probe below is the real test.
        _, _, codec = name.partition(".")
        norm = codec.lower().replace("-", "").replace("_", "")
        if not norm or norm in {"utf8", "utf8mb4"} or name in {"C", "POSIX"}:
            continue
        try:
            check = subprocess.run(
                [sys.executable, "-c", probe],
                env={"LC_ALL": name, "PATH": "/usr/bin:/bin"},
                capture_output=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if check.returncode == 0:   # its decoder really does reject UTF-8
            return name
    return None


# --- the real reproduction, where the machine has a non-UTF-8 locale ---------

def test_yap_transcript_survives_a_non_utf8_locale(tmp_path):
    """End-to-end: a Korean transcript from yap must round-trip under eucKR."""
    locale_name = _non_utf8_locale()
    if locale_name is None:
        pytest.skip("no non-UTF-8 multibyte locale installed (see the contract test below)")

    fake_yap = tmp_path / "yap"
    fake_yap.write_text(
        "#!/bin/sh\n"
        f"printf 'WEBVTT\\n\\n00:01.000 --> 00:02.000\\n{KOREAN}\\n'\n",
        encoding="utf-8",
    )
    fake_yap.chmod(0o755)

    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import sys, json
            sys.path.insert(0, {str(SCRIPTS)!r})
            from transcription import TranscriptionRequest
            from transcription_adapters import YapAdapter
            from transcription_chunks import AudioChunk, PreparedAudio

            work = {str(tmp_path / "work")!r}
            audio = {str(tmp_path / "chunk.mp3")!r}
            open(audio, "wb").write(b"audio")
            chunk = AudioChunk(index=0, path=__import__("pathlib").Path(audio),
                               source_offset=30.0, duration=5.0, sha256="abc")
            request = TranscriptionRequest(
                media_path=__import__("pathlib").Path({str(tmp_path / "clip.mp4")!r}),
                work_dir=__import__("pathlib").Path(work),
                adapter_order=(), allow_remote=False, config={{"receipts": False}},
                prepared_audio=PreparedAudio(__import__("pathlib").Path(audio), (chunk,), 30.0, 35.0),
            )
            segments = YapAdapter(executable={str(fake_yap)!r})._transcribe_one(request, chunk)
            sys.stdout.buffer.write(json.dumps(segments, ensure_ascii=False).encode("utf-8"))
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "clip.mp4").write_bytes(b"media")

    proc = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        env={"LC_ALL": locale_name, "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=120,
    )
    stderr = proc.stderr.decode("utf-8", "replace")
    assert "UnicodeDecodeError" not in stderr, (
        f"transcript decode still follows the {locale_name} locale:\n{stderr}"
    )
    assert proc.returncode == 0, stderr
    segments = json.loads(proc.stdout.decode("utf-8"))
    assert KOREAN in segments[0]["text"], f"transcript text was mangled: {segments}"


# --- contract tests: these can never silently skip ---------------------------

def _kwargs_of(monkeypatch, module, call):
    """Record the kwargs the module passes to subprocess.run."""
    seen = {}

    class Result:
        returncode = 0
        stdout = "WEBVTT\n\n00:01.000 --> 00:02.000\nwords\n"
        stderr = ""

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    call()
    return seen


def test_yap_content_decode_is_utf8_and_stays_loud(monkeypatch, tmp_path):
    """The content path must NOT swallow a decode failure into U+FFFD."""
    monkeypatch.setattr(adapters.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(adapters.shutil, "which", lambda name: "/opt/homebrew/bin/yap")
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = chunks.AudioChunk(index=0, path=audio, source_offset=30.0, duration=5.0, sha256="abc")
    request = adapters_request(tmp_path)

    kwargs = _kwargs_of(
        monkeypatch, adapters,
        lambda: adapters.YapAdapter()._transcribe_one(request, chunk),
    )
    assert kwargs.get("encoding") == "utf-8", "yap stdout is the transcript; pin the codec"
    assert "errors" not in kwargs or kwargs["errors"] == "strict", (
        "errors='replace' on the transcript path writes mojibake out as a "
        "valid-looking transcript — a failure that exits 0"
    )


def test_diagnostic_paths_decode_utf8_and_replace(monkeypatch, tmp_path):
    """Output nobody parses must never crash a run: replace is correct there."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"media")

    ev = _kwargs_of(
        monkeypatch, evidence,
        lambda: evidence.extract_frame(str(video), 1.0, tmp_path / "f.jpg"),
    )
    assert ev.get("encoding") == "utf-8"
    assert ev.get("errors") == "replace"

    ch = _kwargs_of(
        monkeypatch, chunks,
        lambda: chunks._run_ffmpeg(["ffmpeg", "-i", str(video)], failure="probe"),
    )
    assert ch.get("encoding") == "utf-8"
    assert ch.get("errors") == "replace"


def test_http_transcript_bodies_decode_strictly():
    """Codex round 1, P2: both HTTP transcript paths accepted U+FFFD as words.

    `response.read().decode("utf-8", errors="replace")` turned invalid bytes
    inside a JSON transcript string into real-looking text ("hello �")
    that flowed out as an accepted segment. Content decodes strictly.
    """
    for path in (SCRIPTS / "transcription_adapters.py", SCRIPTS / "whisper.py"):
        source = path.read_text(encoding="utf-8")
        assert 'read().decode("utf-8", errors="replace")' not in source, (
            f"{path.name} decodes a transcript body with errors='replace'; "
            "that writes invented characters into quoted evidence"
        )


def test_no_subprocess_decodes_by_locale():
    """No child-process call may decode with the system locale.

    Round 1 (Codex): the regex audit missed nested-paren and injected-runner
    calls. Round 2 (Codex) showed the first ast version still gave FALSE PASSES
    on `encoding=None`, `errors=` without `encoding=`, a `**{...}` splat, and
    `from subprocess import run`. Each is closed here; an unauditable call
    fails closed rather than being waved through.
    """
    import ast

    problems = []
    for file in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"), str(file))
        # names bound to subprocess callables in THIS file (catches
        # `from subprocess import run` / `import subprocess as sp`)
        callees = {"subprocess.run", "subprocess.Popen", "subprocess.check_output", "runner"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                for alias in node.names:
                    if alias.name in {"run", "Popen", "check_output"}:
                        callees.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" and alias.asname:
                        for fn in ("run", "Popen", "check_output"):
                            callees.add(f"{alias.asname}.{fn}")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) not in callees:
                continue
            where = f"{file.name}:{node.lineno}"
            if any(k.arg is None for k in node.keywords):     # **splat
                problems.append(f"{where} (**kwargs splat, cannot audit)")
                continue
            kw = {k.arg: k.value for k in node.keywords}
            # text mode is on if ANY of these is set (errors= alone enables it)
            text_mode = (
                any(ast.unparse(kw[k]) == "True" for k in ("text", "universal_newlines") if k in kw)
                or "errors" in kw or "encoding" in kw
            )
            if not text_mode:
                continue
            enc = kw.get("encoding")
            if enc is None or (isinstance(enc, ast.Constant) and enc.value is None):
                problems.append(f"{where} (text mode with no explicit encoding)")
    assert not problems, (
        "these decode child output with the system locale, so a non-UTF-8 "
        f"console crashes them on the first non-ASCII byte: {problems}"
    )


def test_ytdlp_version_probe_decodes_utf8(monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = "2026.08.19"
        stderr = ""

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    setup_mod._ytdlp_age_days()
    assert seen.get("encoding") == "utf-8"


def adapters_request(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"audio")
    chunk = chunks.AudioChunk(index=0, path=audio, source_offset=30.0, duration=5.0, sha256="abc")
    from transcription import TranscriptionRequest

    return TranscriptionRequest(
        media_path=media,
        work_dir=tmp_path / "work",
        adapter_order=(),
        allow_remote=False,
        config={"receipts": False},
        prepared_audio=chunks.PreparedAudio(audio, (chunk,), 30.0, 35.0),
    )
