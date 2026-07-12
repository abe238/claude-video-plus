#!/usr/bin/env python3
"""Run the frozen upstream Control without changing its checkout.

This is deliberately a small, standalone harness.  It constructs the only
permitted Control command itself instead of accepting a shell command, and it
keeps every generated file outside the detached Control worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CONTROL_COMMIT = "83da59fa78c3eee9e20f515fe75c438bb5166efd"
CONTROL_SCRIPT = "skills/watch/scripts/watch.py"
CASE_SCHEMA_VERSION = 1
ALLOWED_FLAG_NAMES = {
    "detail", "max_frames", "resolution", "fps", "timestamps", "start", "end",
    "no_whisper", "whisper", "no_dedup",
}
REQUIRED_FLAG_NAMES = frozenset(ALLOWED_FLAG_NAMES)
REQUIRED_TOOLS = ("python", "ffmpeg", "ffprobe", "yt_dlp")
GIT_EXECUTABLE = "/usr/bin/git"


class ControlIntegrityError(RuntimeError):
    """A Control precondition failed, so no comparable result may be used."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _isolated_environment(home: Path, path: str) -> dict[str, str]:
    """Return the complete allowlist for a subprocess; inherit nothing."""
    return {
        "PATH": path,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LC_ALL": "C",
        "LANG": "C",
    }


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git without caller-controlled repository/config selection variables."""
    with tempfile.TemporaryDirectory(prefix="watch-control-git-") as temporary_home:
        return subprocess.run(
            [GIT_EXECUTABLE, *args], cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=check,
            env=_isolated_environment(Path(temporary_home), "/usr/bin:/bin"),
        )


def _require_absolute_executable(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ControlIntegrityError(f"missing pinned {label} executable")
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ControlIntegrityError(f"pinned {label} executable is not an executable absolute path")
    return path


def _version_line(path: Path, argument: str, environment: dict[str, str]) -> str:
    try:
        result = subprocess.run(
            [str(path), argument], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False, timeout=15, env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlIntegrityError(f"cannot inspect pinned tool {path}: {exc}") from exc
    line = result.stdout.splitlines()[0] if result.stdout else ""
    if result.returncode != 0 or not line:
        raise ControlIntegrityError(f"cannot obtain a version from pinned tool {path}")
    return line


def capture_tool_versions(paths: dict[str, str]) -> dict[str, str]:
    """Return exact first-line versions for a fully pinned tool map."""
    arguments = {"python": "--version", "ffmpeg": "-version", "ffprobe": "-version", "yt_dlp": "--version"}
    with tempfile.TemporaryDirectory(prefix="watch-control-probe-") as temporary_home:
        environment = _isolated_environment(Path(temporary_home), "/usr/bin:/bin")
        return {
            name: _version_line(_require_absolute_executable(paths.get(name), name), arguments[name], environment)
            for name in REQUIRED_TOOLS
        }


def capture_tool_sha256(paths: dict[str, str]) -> dict[str, str]:
    """Return content hashes for the fully pinned executable map."""
    return {
        name: hashlib.sha256(_require_absolute_executable(paths.get(name), name).read_bytes()).hexdigest()
        for name in REQUIRED_TOOLS
    }


def paired_order(case_id: str) -> tuple[str, str]:
    """Return the preregistered Control/Candidate order for one case ID."""
    if not isinstance(case_id, str) or not case_id.strip():
        raise ControlIntegrityError("case_id is required to determine paired order")
    first = "control" if hashlib.sha256(case_id.encode("utf-8")).digest()[0] % 2 == 0 else "candidate"
    return (first, "candidate" if first == "control" else "control")


def assert_clean_detached_control(worktree: Path, control_commit: str | None = None) -> None:
    """Reject any checkout that is not the exact, clean, detached Control."""
    control_commit = control_commit or CONTROL_COMMIT
    if not worktree.is_dir():
        raise ControlIntegrityError(f"Control worktree does not exist: {worktree}")
    try:
        head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ControlIntegrityError(f"not a usable Git worktree: {worktree}") from exc
    if head != control_commit:
        raise ControlIntegrityError(f"Control worktree is at {head}, expected {control_commit}")
    if _git(worktree, "symbolic-ref", "-q", "HEAD", check=False).returncode == 0:
        raise ControlIntegrityError("Control worktree must be detached")
    status = _git(
        worktree, "status", "--porcelain=v1", "--untracked-files=all", "--ignored",
    ).stdout
    if status:
        raise ControlIntegrityError("Control worktree is dirty")
    if not (worktree / CONTROL_SCRIPT).is_file():
        raise ControlIntegrityError(f"Control script is missing: {CONTROL_SCRIPT}")


def prepare_worktree(repo: Path, worktree: Path, control_commit: str | None = None) -> Path:
    """Create, or verify, a clean detached worktree at the immutable Control."""
    control_commit = control_commit or CONTROL_COMMIT
    repo = repo.resolve()
    worktree = worktree.resolve()
    if worktree.exists():
        assert_clean_detached_control(worktree, control_commit)
        return worktree
    if not repo.is_dir():
        raise ControlIntegrityError(f"repository does not exist: {repo}")
    try:
        _git(repo, "cat-file", "-e", f"{control_commit}^{{commit}}")
        _git(repo, "worktree", "add", "--detach", str(worktree), control_commit)
    except subprocess.CalledProcessError as exc:
        raise ControlIntegrityError(f"cannot create frozen Control worktree: {exc.stderr.strip()}") from exc
    assert_clean_detached_control(worktree, control_commit)
    return worktree


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ControlIntegrityError(f"{label} must be an object")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_http_source(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _select_frozen_control_subtitle(download_dir: Path) -> Path | None:
    """Apply the frozen Control's unchanged ``download._pick_subtitle`` rule.

    At 83da59f the upstream helper sorts ``video*.vtt`` and then selects the
    first filename containing ``.en.``, ``.en-US.``, ``.en-GB.``, or
    ``.en-orig.``; otherwise it selects the first sorted candidate.
    """
    candidates = sorted(download_dir.glob("video*.vtt"))
    if not candidates:
        return None
    preferred = [
        candidate for candidate in candidates
        if any(marker in candidate.name for marker in (".en.", ".en-US.", ".en-GB.", ".en-orig."))
    ]
    return preferred[0] if preferred else candidates[0]


def validate_case(case: dict[str, Any]) -> None:
    """Validate all policy inputs before the Control process can start."""
    if case.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ControlIntegrityError("unsupported or missing Control case schema_version")
    if not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
        raise ControlIntegrityError("case_id is required")
    if not isinstance(case.get("source"), str) or not case["source"]:
        raise ControlIntegrityError("source is required")
    if case.get("question") is not None and not isinstance(case.get("question"), str):
        raise ControlIntegrityError("question must be a string or null")
    source_identity = _require_mapping(case.get("source_identity"), "source_identity")
    if set(source_identity) != {"kind", "identity_sha256", "caption_sha256"}:
        raise ControlIntegrityError("source_identity must contain exactly kind, identity_sha256, and caption_sha256")
    if source_identity.get("kind") not in {"local", "url"}:
        raise ControlIntegrityError("source_identity.kind must be local or url")
    identity_hash = source_identity.get("identity_sha256")
    if "caption_path" in source_identity:
        raise ControlIntegrityError(
            "caption_path is not an input: Control caption identity is verified after its own selection"
        )
    if "caption_sha256" not in source_identity:
        raise ControlIntegrityError("source_identity.caption_sha256 must explicitly pin a caption hash or null")
    caption_hash = source_identity["caption_sha256"]
    if not isinstance(identity_hash, str) or len(identity_hash) != 64 or any(c not in "0123456789abcdef" for c in identity_hash):
        raise ControlIntegrityError("source_identity.identity_sha256 must be a lowercase SHA-256")
    if caption_hash is not None and (not isinstance(caption_hash, str) or len(caption_hash) != 64
            or any(c not in "0123456789abcdef" for c in caption_hash)):
        raise ControlIntegrityError("source_identity.caption_sha256 must be null or a lowercase SHA-256")
    if source_identity["kind"] == "local" and _is_http_source(case["source"]):
        raise ControlIntegrityError("local source_identity cannot name an HTTP(S) URL")
    if source_identity["kind"] == "url" and not _is_http_source(case["source"]):
        raise ControlIntegrityError("URL source_identity must name an HTTP(S) URL")
    if source_identity["kind"] == "local":
        source_path = Path(case["source"])
        if not source_path.is_absolute() or not source_path.is_file():
            raise ControlIntegrityError("local source must be an existing absolute file")
        observed_source_hash = _sha256(source_path.read_bytes())
        if observed_source_hash != identity_hash:
            raise ControlIntegrityError("local source identity_sha256 drifted")
        if caption_hash is not None:
            raise ControlIntegrityError("local Control does not consume a sidecar caption; caption_sha256 must be null")
    elif _sha256(case["source"].encode("utf-8")) != identity_hash:
        raise ControlIntegrityError("URL source identity_sha256 drifted")

    flags = _require_mapping(case.get("frozen_flags"), "frozen_flags")
    if set(flags) != REQUIRED_FLAG_NAMES:
        missing = sorted(REQUIRED_FLAG_NAMES - set(flags))
        unknown = sorted(set(flags) - REQUIRED_FLAG_NAMES)
        raise ControlIntegrityError(f"frozen_flags must pin exactly supported flags; missing={missing}, unknown={unknown}")
    if flags["detail"] not in {"transcript", "efficient", "balanced", "token-burner"}:
        raise ControlIntegrityError("frozen_flags.detail is not a Control detail mode")
    if not isinstance(flags["resolution"], int) or flags["resolution"] < 1:
        raise ControlIntegrityError("frozen_flags.resolution must be a positive integer")
    if flags["max_frames"] is not None and (not isinstance(flags["max_frames"], int) or flags["max_frames"] < 1):
        raise ControlIntegrityError("frozen_flags.max_frames must be null or a positive integer")
    if flags["fps"] is not None and (not isinstance(flags["fps"], (int, float)) or flags["fps"] <= 0):
        raise ControlIntegrityError("frozen_flags.fps must be null or a positive number")
    for name in ("timestamps", "start", "end", "whisper"):
        if flags[name] is not None and not isinstance(flags[name], str):
            raise ControlIntegrityError(f"frozen_flags.{name} must be a string or null")
    if flags["whisper"] not in {None, "groq", "openai"}:
        raise ControlIntegrityError("frozen_flags.whisper is not a supported backend")
    for name in ("no_whisper", "no_dedup"):
        if not isinstance(flags[name], bool):
            raise ControlIntegrityError(f"frozen_flags.{name} must be boolean")
    if not flags["no_whisper"] or flags["whisper"] is not None:
        raise ControlIntegrityError("Control harness requires Whisper disabled until a secret-safe pin exists")

    environment = _require_mapping(case.get("environment"), "environment")
    tools = _require_mapping(environment.get("tools"), "environment.tools")
    versions = _require_mapping(environment.get("tool_versions"), "environment.tool_versions")
    content_hashes = _require_mapping(environment.get("tool_sha256"), "environment.tool_sha256")
    if (set(tools) != set(REQUIRED_TOOLS) or set(versions) != set(REQUIRED_TOOLS)
            or set(content_hashes) != set(REQUIRED_TOOLS)):
        raise ControlIntegrityError(
            "environment must pin python, ffmpeg, ffprobe, and yt_dlp paths, versions, and content hashes"
        )
    for name in REQUIRED_TOOLS:
        _require_absolute_executable(tools[name], name)
        if not isinstance(versions[name], str) or not versions[name]:
            raise ControlIntegrityError(f"missing pinned {name} version")
        content_hash = content_hashes[name]
        if (not isinstance(content_hash, str) or len(content_hash) != 64
                or any(char not in "0123456789abcdef" for char in content_hash)):
            raise ControlIntegrityError(f"missing pinned {name} content SHA-256")
    if environment.get("os") != platform.system() or environment.get("architecture") != platform.machine():
        raise ControlIntegrityError("pinned OS/architecture does not match this environment")
    if not isinstance(environment.get("locale"), str) or not environment["locale"]:
        raise ControlIntegrityError("environment.locale is required")
    if environment.get("network_policy") not in {"offline", "enabled"}:
        raise ControlIntegrityError("environment.network_policy must be offline or enabled")
    if environment.get("network_policy") == "offline" and _is_http_source(case["source"]):
        raise ControlIntegrityError("offline policy cannot run a URL source")
    if environment.get("cookie_input_policy") != "none":
        raise ControlIntegrityError("Control harness permits no cookie input")
    if not isinstance(environment.get("timeout_seconds"), int) or environment["timeout_seconds"] < 1:
        raise ControlIntegrityError("environment.timeout_seconds must be a positive integer")
    invocation = _require_mapping(environment.get("invocation_policy"), "environment.invocation_policy")
    if set(invocation) != {"harness_attempts"}:
        raise ControlIntegrityError("invocation_policy permits only harness_attempts")
    if invocation.get("harness_attempts") != 1:
        raise ControlIntegrityError("Control harness must pin exactly one upstream invocation")

    reader = _require_mapping(case.get("reader"), "reader")
    if not isinstance(reader.get("model_epoch"), str) or not reader["model_epoch"]:
        raise ControlIntegrityError("reader.model_epoch is required")
    prompt_hash = reader.get("prompt_sha256")
    if not isinstance(prompt_hash, str) or len(prompt_hash) != 64 or any(c not in "0123456789abcdef" for c in prompt_hash):
        raise ControlIntegrityError("reader.prompt_sha256 must be a lowercase SHA-256")


def _verify_versions(case: dict[str, Any]) -> dict[str, Path]:
    environment = case["environment"]
    paths = {name: _require_absolute_executable(environment["tools"][name], name) for name in REQUIRED_TOOLS}
    observed_hashes = capture_tool_sha256({name: str(path) for name, path in paths.items()})
    for name, value in observed_hashes.items():
        if value != environment["tool_sha256"][name]:
            raise ControlIntegrityError(f"pinned {name} executable content drifted")
    observed = capture_tool_versions({name: str(path) for name, path in paths.items()})
    for name, value in observed.items():
        if value != environment["tool_versions"][name]:
            raise ControlIntegrityError(f"pinned {name} version drifted: {value!r}")
    return paths


def _empty_external_directory(path: Path, worktree: Path, label: str) -> Path:
    path = path.resolve()
    try:
        path.relative_to(worktree.resolve())
    except ValueError:
        pass
    else:
        raise ControlIntegrityError(f"{label} must be outside the Control worktree")
    if path.exists() and any(path.iterdir()):
        raise ControlIntegrityError(f"{label} must be empty")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _directories_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _build_command(case: dict[str, Any], tool_paths: dict[str, Path], out_dir: Path) -> list[str]:
    flags = case["frozen_flags"]
    command = [str(tool_paths["python"]), CONTROL_SCRIPT, case["source"], "--detail", flags["detail"], "--resolution", str(flags["resolution"])]
    optional = (("max_frames", "--max-frames"), ("fps", "--fps"), ("timestamps", "--timestamps"), ("start", "--start"), ("end", "--end"), ("whisper", "--whisper"))
    for name, argument in optional:
        if flags[name] is not None:
            command.extend((argument, str(flags[name])))
    if flags["no_whisper"]:
        command.append("--no-whisper")
    if flags["no_dedup"]:
        command.append("--no-dedup")
    command.extend(("--out-dir", str(out_dir)))
    return command


def _manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            rows.append({
                "path": item.relative_to(path).as_posix(),
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                "bytes": item.stat().st_size,
            })
    return rows


def _verify_consumed_caption(case: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Verify the exact subtitle captured immediately after a frozen yt-dlp call."""
    expected = case["source_identity"]["caption_sha256"]
    snapshot_root = out_dir
    selected = None
    for call_dir in sorted(snapshot_root.glob("call-*"), key=lambda path: int(path.name.split("-")[1])):
        candidate = _select_frozen_control_subtitle(call_dir)
        if candidate is None:
            continue
        # Frozen Control consumes the first selected VTT that parses to at
        # least one segment.  Empty/invalid captions fall through to a later
        # download call.
        if _frozen_vtt_has_segments(candidate):
            selected = candidate
            break
    observed = _sha256(selected.read_bytes()) if selected is not None else None
    relative = selected.relative_to(snapshot_root).as_posix() if selected is not None else None
    result = {
        "expected_sha256": expected,
        "selected_path": relative,
        "selected_sha256": observed,
    }
    if observed != expected:
        raise ControlIntegrityError(
            f"Control consumed caption identity drifted: expected {expected!r}, observed {observed!r}"
        )
    return result


def _frozen_vtt_has_segments(path: Path) -> bool:
    """Apply the frozen parser's cue rule without importing or modifying Control."""
    import re
    timestamp = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
    )
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for index, line in enumerate(lines[:-1]):
        if timestamp.match(line):
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].strip():
                if re.sub(r"<[^>]+>", "", lines[cursor]).strip():
                    return True
                cursor += 1
    return False


def _write_ytdlp_wrapper(path: Path, real_tool: Path, snapshot_root: Path) -> str:
    """Wrap frozen yt-dlp calls and snapshot VTT bytes before Control resumes."""
    script = f"""#!/bin/sh
real={shlex.quote(str(real_tool))}
root={shlex.quote(str(snapshot_root))}
"$real" "$@"
status=$?
template=
want_output=0
for arg in "$@"; do
  if [ "$want_output" = 1 ]; then template=$arg; want_output=0; continue; fi
  case "$arg" in
    -o|--output) want_output=1 ;;
    --output=*) template=${{arg#--output=}} ;;
  esac
done
if [ -n "$template" ]; then
  source_dir=$(dirname "$template")
  index=1
  while ! mkdir "$root/call-$index" 2>/dev/null; do index=$((index + 1)); done
  for file in "$source_dir"/video*.vtt; do
    [ -f "$file" ] && cp "$file" "$root/call-$index/"
  done
fi
exit "$status"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return _sha256(path.read_bytes())


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_in_process_group(command: list[str], worktree: Path, environment: dict[str, str], timeout: int) -> tuple[int, bytes, bytes, bool]:
    """Run one Control process and reap its entire process group on timeout."""
    process = subprocess.Popen(
        command, cwd=worktree, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        _terminate_process_group(process, signal.SIGTERM)
        communicated = False
        try:
            stdout, stderr = process.communicate(timeout=5)
            communicated = True
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        # A descendant can ignore TERM, close its inherited pipes, and outlive
        # a leader whose communicate() already returned. Always deliver the
        # final group kill, then reap the leader's pipes if necessary.
        _terminate_process_group(process, signal.SIGKILL)
        if _process_group_exists(process.pid):
            _terminate_process_group(process, signal.SIGKILL)
        if not communicated:
            stdout, stderr = process.communicate()
        return 124, stdout, stderr, True


def _terminate_process_group(process: subprocess.Popen[bytes], signal_number: signal.Signals) -> None:
    """Signal a timed-out process group; it may have exited between timeout and signal."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal_number)
        elif signal_number == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()
    except PermissionError:
        # Some hosted macOS runners refuse killpg after the leader exits. Kill
        # same-user members individually using the recorded process-group id.
        result = subprocess.run(["ps", "-axo", "pid=,pgid="], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            try:
                pid, group = (int(value) for value in line.split())
                if group == process.pid and pid != os.getpid():
                    os.kill(pid, signal_number)
            except (ValueError, ProcessLookupError, PermissionError):
                continue
    except ProcessLookupError:
        pass


def _process_group_exists(process_group: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.killpg(process_group, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def run_control(
    case: dict[str, Any], worktree: Path, out_dir: Path, receipt_dir: Path,
    control_commit: str | None = None,
) -> dict[str, Any]:
    """Run one Control arm and preserve its unmodified raw output tree and logs."""
    control_commit = control_commit or CONTROL_COMMIT
    validate_case(case)
    worktree = worktree.resolve()
    assert_clean_detached_control(worktree, control_commit)
    tool_paths = _verify_versions(case)
    resolved_out_dir = out_dir.resolve()
    resolved_receipt_dir = receipt_dir.resolve()
    if _directories_overlap(resolved_out_dir, resolved_receipt_dir):
        raise ControlIntegrityError("Control output and receipt directories must not overlap")
    out_dir = _empty_external_directory(resolved_out_dir, worktree, "Control output directory")
    receipt_dir = _empty_external_directory(resolved_receipt_dir, worktree, "Control receipt directory")
    shims = receipt_dir / "pinned-tools"
    shims.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (shims / name).symlink_to(tool_paths[name])
    caption_snapshots = receipt_dir / "caption-snapshots"
    caption_snapshots.mkdir()
    wrapper_sha256 = _write_ytdlp_wrapper(shims / "yt-dlp", tool_paths["yt_dlp"], caption_snapshots)

    command = _build_command(case, tool_paths, out_dir)
    isolated_home = receipt_dir / "isolated-home"
    isolated_home.mkdir(mode=0o700)
    environment = _isolated_environment(isolated_home, f"{shims}{os.pathsep}/usr/bin{os.pathsep}/bin")
    environment.update({
        "LC_ALL": case["environment"]["locale"], "LANG": case["environment"]["locale"],
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    started = _utc_now()
    exit_code, stdout, stderr, timed_out = _run_in_process_group(
        command, worktree, environment, case["environment"]["timeout_seconds"],
    )
    ended = _utc_now()
    (receipt_dir / "stdout.raw").write_bytes(stdout)
    (receipt_dir / "stderr.raw").write_bytes(stderr)
    integrity_failures: list[str] = []
    control_clean_after = True
    caption_result: dict[str, Any]
    try:
        caption_result = _verify_consumed_caption(case, caption_snapshots)
    except ControlIntegrityError as exc:
        caption_result = {"expected_sha256": case["source_identity"]["caption_sha256"], "selected_path": None, "selected_sha256": None}
        selected = None
        for call_dir in sorted(caption_snapshots.glob("call-*")):
            candidate = _select_frozen_control_subtitle(call_dir)
            if candidate is not None and _frozen_vtt_has_segments(candidate):
                selected = candidate
                break
        if selected is not None:
            caption_result["selected_path"] = selected.relative_to(caption_snapshots).as_posix()
            caption_result["selected_sha256"] = _sha256(selected.read_bytes())
        integrity_failures.append(str(exc))
    try:
        assert_clean_detached_control(worktree, control_commit)
    except ControlIntegrityError as exc:
        control_clean_after = False
        integrity_failures.append(str(exc))
    order = paired_order(case["case_id"])
    receipt = {
        "schema_version": CASE_SCHEMA_VERSION,
        "artifact_type": "control_run_receipt",
        "control_commit": control_commit,
        "case_id": case["case_id"],
        "paired_order": list(order),
        "control_order": order.index("control") + 1,
        "command": command,
        "environment": {
            "os": case["environment"]["os"], "architecture": case["environment"]["architecture"],
            "locale": case["environment"]["locale"], "network_policy": case["environment"]["network_policy"],
            "cookie_input_policy": case["environment"]["cookie_input_policy"],
            "invocation_policy": case["environment"]["invocation_policy"],
            "tools": {name: str(path) for name, path in tool_paths.items()},
            "tool_versions": case["environment"]["tool_versions"],
            "tool_sha256": case["environment"]["tool_sha256"],
            "yt_dlp_wrapper_sha256": wrapper_sha256,
        },
        "reader": case["reader"], "source_identity": case["source_identity"],
        "consumed_caption": caption_result,
        "started_at_utc": started, "ended_at_utc": ended, "exit_code": exit_code,
        "timed_out": timed_out, "raw_stdout": "stdout.raw", "raw_stderr": "stderr.raw",
        "raw_output_manifest": _manifest(out_dir), "control_clean_after": control_clean_after,
        "integrity_failure": "; ".join(integrity_failures) if integrity_failures else None,
    }
    _write_json(receipt_dir / "run.json", receipt)
    if integrity_failures:
        raise ControlIntegrityError(f"Control integrity refusal after run: {'; '.join(integrity_failures)}")
    return receipt


def _load_case(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlIntegrityError(f"cannot read case record: {exc}") from exc
    if not isinstance(data, dict):
        raise ControlIntegrityError("case record must be a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare", help="create or verify the detached frozen Control")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--worktree", type=Path, required=True)
    run = subcommands.add_parser("run", help="run one immutable Control arm from a pinned case record")
    run.add_argument("--case", type=Path, required=True)
    run.add_argument("--worktree", type=Path, required=True)
    run.add_argument("--out-dir", type=Path, required=True)
    run.add_argument("--receipt-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(prepare_worktree(args.repo, args.worktree))
        else:
            receipt = run_control(_load_case(args.case), args.worktree, args.out_dir, args.receipt_dir)
            print(json.dumps({"receipt": str(args.receipt_dir / "run.json"), "exit_code": receipt["exit_code"]}))
    except ControlIntegrityError as exc:
        print(f"control-harness: integrity refusal: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
