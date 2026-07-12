#!/usr/bin/env python3
"""P02 routing and behavioral conformance for the immutable upstream Control.

This module deliberately has two narrow entry points.  ``route_control`` receives
only pre-outcome user inputs.  ``run_pair`` receives a complete P01 Control case
and constructs both commands itself; it never accepts a caller supplied command.
It is a compatibility check, not a benchmark or an alternate Control.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:  # support the documented `python3 tools/...` form
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import control_harness


ROUTING_VERSION = "cheapest-control-v1"
CONTROL_DETAILS = frozenset(("transcript", "efficient", "balanced", "token-burner"))
MIRRORED_FLAGS = frozenset((
    "max_frames", "resolution", "fps", "timestamps", "start", "end",
    "no_whisper", "whisper", "no_dedup",
))
SOURCE_METADATA_FIELDS = frozenset(("kind", "identity_sha256"))
ALLOWED_DIFFERENCES = frozenset(("temporary_paths", "evidence_fallback_warning"))
VISUAL_RE = re.compile(
    r"\b(?:visible|visual|ui|user interface|on[- ]screen|screen|text|table|"
    r"object|motion|transition|before\s*(?:and|[-/]?)\s*after|graph|chart|plot|"
    r"car\s+(?:move|movement|moving)|person\s+(?:walk|walks|walking)|"
    r"object\s+(?:move|motion|moving)|logo\s+(?:looks?|appears?)|"
    r"animation\s+(?:does|show|shows)|what\s+changed)\b", re.I)
COVERAGE_RE = re.compile(r"\b(?:coverage|summary|summar(?:y|ize)|all topics|everything|chronology|timeline)\b", re.I)
SAID_RE = re.compile(r"\b(?:said|say|explained|explain|spoken|tell me)\b", re.I)
FRAME_LINE_RE = re.compile(r"^\s*-?\s*.*?/frames/(frame_[^\s`)]+).*?\(t=([^,)]+)(?:,\s*reason=([^)]*))?\)", re.M)
TRANSCRIPT_LINE_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.M)
ABS_PATH_RE = re.compile(r"(?<![\w:])/(?:[^\s`)>]+/)+[^\s`)>]+")


class ConformanceRefusal(RuntimeError):
    """The comparison is not valid and therefore must not produce a verdict."""


@dataclass(frozen=True)
class RoutingRequest:
    """The complete, outcome-free routing input boundary.

    No transcript, chapters, scores, gold labels, evidence, result, or observed
    outcome field exists in this type.  The public function has no ``**kwargs``.
    """
    question: str | None
    explicit_detail: str | None = None
    timestamps: str | None = None
    mirrored_flags: Mapping[str, Any] | None = None
    source_metadata: Mapping[str, str] | None = None


def _refuse(condition: bool, message: str) -> None:
    if condition:
        raise ConformanceRefusal(message)


def _seconds(value: str, label: str) -> float:
    parts = value.split(":")
    _refuse(not 1 <= len(parts) <= 3, f"invalid {label}")
    _refuse(any(not re.fullmatch(r"\d+(?:\.\d+)?", part) for part in parts), f"invalid {label}")
    _refuse(any("." in part for part in parts[:-1]), f"invalid {label}")
    values = [float(part) for part in parts]
    _refuse(len(values) > 1 and values[-1] >= 60, f"invalid {label}")
    _refuse(len(values) > 2 and values[-2] >= 60, f"invalid {label}")
    return float(sum(item * 60 ** index for index, item in enumerate(reversed(values))))


def _validate_flag(name: str, value: Any) -> None:
    if name in {"max_frames", "resolution"}:
        _refuse(isinstance(value, bool) or not isinstance(value, int) or value < 1, f"invalid {name}")
    elif name == "fps":
        _refuse(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0, "invalid fps")
    elif name in {"timestamps", "start", "end"}:
        _refuse(not isinstance(value, str) or not value.strip(), f"invalid {name}")
        values = value.split(",") if name == "timestamps" else [value]
        for item in values:
            _seconds(item.strip(), name)
    elif name == "whisper":
        _refuse(value not in {"groq", "openai"}, "invalid whisper")
    elif name in {"no_whisper", "no_dedup"}:
        _refuse(not isinstance(value, bool), f"invalid {name}")


def _validated_routing_input(request: RoutingRequest) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    _refuse(not isinstance(request, RoutingRequest), "routing requires a RoutingRequest")
    _refuse(request.question is not None and (not isinstance(request.question, str) or not request.question.strip()),
            "Question must be complete non-empty text or null")
    detail = request.explicit_detail
    _refuse(detail is not None and detail not in CONTROL_DETAILS,
            "explicit detail is unknown or unsupported by frozen Control")
    if request.timestamps is not None:
        _validate_flag("timestamps", request.timestamps)
    _refuse(request.mirrored_flags is not None and not isinstance(request.mirrored_flags, Mapping),
            "mirrored_flags must be a mapping")
    flags = dict(request.mirrored_flags or {})
    _refuse(set(flags) - MIRRORED_FLAGS, "unknown or outcome-derived routing flag")
    for name, value in flags.items():
        _validate_flag(name, value)
    _refuse(flags.get("no_whisper") is True and "whisper" in flags, "whisper conflicts with no_whisper")
    _refuse("start" in flags and "end" in flags and _seconds(flags["end"], "end") <= _seconds(flags["start"], "start"),
            "end must be greater than start")
    timestamps = request.timestamps if request.timestamps is not None else flags.get("timestamps")
    if request.timestamps is not None:
        _refuse("timestamps" in flags and flags["timestamps"] != request.timestamps,
                "explicit timestamps disagree with mirrored timestamps")
        flags["timestamps"] = request.timestamps
    metadata = request.source_metadata
    if metadata is not None:
        _refuse(not isinstance(metadata, Mapping) or set(metadata) != SOURCE_METADATA_FIELDS,
                "source metadata includes unsupported or outcome-derived fields")
        _refuse(metadata.get("kind") not in {"local", "url"}, "source metadata kind is invalid")
        _refuse(not isinstance(metadata.get("identity_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", metadata["identity_sha256"]),
                "source metadata identity_sha256 is invalid")
        _refuse(any(not isinstance(value, str) or not value for value in metadata.values()),
                "source metadata is ambiguous")
    return request.question, detail, timestamps, flags


def route_control(request: RoutingRequest) -> dict[str, Any]:
    """Apply CONTROL.md priorities 1–6 before media analysis."""
    question, explicit_detail, timestamps, flags = _validated_routing_input(request)
    if explicit_detail is not None:
        rule, detail = 1, explicit_detail
    elif timestamps is not None:
        rule, detail = 2, "transcript"
    elif question and VISUAL_RE.search(question):
        rule, detail = 3, "balanced"
    elif question and COVERAGE_RE.search(question):
        rule, detail = 4, "balanced"
    elif question and SAID_RE.search(question) and not VISUAL_RE.search(question):
        rule, detail = 5, "transcript"
    else:
        rule, detail = 6, "balanced"
    effective = {"detail": detail, **flags}
    return {
        "schema_version": 1,
        "routing_version": ROUTING_VERSION,
        "matched_rule": rule,
        "effective_frozen_control_flags": effective,
    }


def paired_order(case_id: str) -> tuple[str, str]:
    """Use P01's one source of truth for alternating paired order."""
    return control_harness.paired_order(case_id)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(path: Path) -> list[dict[str, Any]]:
    return [
        {"path": item.relative_to(path).as_posix(), "sha256": _sha256_path(item), "bytes": item.stat().st_size}
        for item in sorted(path.rglob("*")) if item.is_file()
    ]


def raw_receipt_hashes(receipt_dir: Path) -> dict[str, str]:
    """Hash the named arm's own captured streams; never depend on loop state."""
    return {"raw_stdout_sha256": _sha256_path(receipt_dir / "stdout.raw"),
            "raw_stderr_sha256": _sha256_path(receipt_dir / "stderr.raw")}


def _jpeg_dimensions(path: Path) -> tuple[int, int] | None:
    """Read baseline/progressive JPEG dimensions without non-stdlib imaging."""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        return None
    cursor = 2
    while cursor + 9 < len(data):
        if data[cursor] != 0xFF:
            cursor += 1
            continue
        marker = data[cursor + 1]
        cursor += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            return None
        if 0xC0 <= marker <= 0xC3:
            return (int.from_bytes(data[cursor + 5:cursor + 7], "big"),
                    int.from_bytes(data[cursor + 3:cursor + 5], "big"))
        cursor += length
    return None


def normalize_text(text: str, roots: tuple[Path, ...]) -> str:
    """Replace only declared volatile roots; unknown absolute paths are refusals."""
    normalized = text
    for root in sorted((str(path.resolve()).replace("\\", "/") for path in roots), key=len, reverse=True):
        normalized = re.sub(re.escape(root) + r"(?:/[^\s`)]+)?", "<TMP_PATH>", normalized)
    _refuse(bool(ABS_PATH_RE.search(normalized)), "undeclared absolute path in observable output")
    return normalized


def summarize_output(out_dir: Path, stdout: str, stderr: str, roots: tuple[Path, ...]) -> dict[str, Any]:
    raw_stdout = stdout
    stdout = normalize_text(raw_stdout, roots)
    stderr = normalize_text(stderr, roots)
    frames = []
    for name, timestamp, reason in FRAME_LINE_RE.findall(raw_stdout):
        path = next(iter(sorted(out_dir.glob(f"frames/{name}"))), None)
        frames.append({"name": name, "timestamp": timestamp, "reason": reason or None,
                       "dimensions": _jpeg_dimensions(path) if path else None})
    transcript = [{"timestamp": stamp, "text": line} for stamp, line in TRANSCRIPT_LINE_RE.findall(stdout)]
    return {"stdout": stdout, "stderr": stderr, "frames": frames, "transcript": transcript,
            "raw_manifest": _manifest(out_dir)}


def classify(exit_code: int, timed_out: bool, summary: Mapping[str, Any]) -> str:
    if timed_out or exit_code == 124:
        return "timeout"
    if exit_code == 0:
        return "success"
    if not summary.get("raw_manifest"):
        return "empty_output"
    return "failure"


def derive_outcome(exit_code: int, timed_out: bool, stdout: str, stderr: str) -> dict[str, Any]:
    """Classify only observed watched-command output, never a fixture label."""
    state = classify(exit_code, timed_out, {"raw_manifest": [1]})
    failure = None
    if state == "timeout":
        failure = "timeout"
    elif state == "failure":
        marker = re.search(r"P02_FAILURE:([a-z0-9_-]+)", stderr)
        failure = marker.group(1) if marker else "runtime_error"
    fallback = ["scene", "uniform"] if "uniform fallback" in stdout else []
    return {"exit_class": state, "failure_class": failure, "fallback_order": fallback}


def compare_summaries(control: Mapping[str, Any], candidate: Mapping[str, Any], *, allowed: frozenset[str] = frozenset({"temporary_paths"})) -> list[str]:
    """Return each undeclared behavioral difference; an empty list conforms."""
    _refuse(not allowed.issubset(ALLOWED_DIFFERENCES), "undeclared allowed difference")
    differences: list[str] = []
    comparable_control = dict(control)
    comparable_candidate = dict(candidate)
    if "evidence_fallback_warning" in allowed:
        comparable_candidate["stderr"] = re.sub(
            r"^\[watch\] evidence mode failed .*? — falling back to balanced\n?", "",
            str(comparable_candidate.get("stderr", "")), flags=re.M)
    for field in ("stdout", "stderr", "frames", "transcript"):
        if comparable_control.get(field) != comparable_candidate.get(field):
            differences.append(field)
    if control.get("raw_manifest", []) != candidate.get("raw_manifest", []):
        differences.append("raw_manifest")
    return differences


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["/usr/bin/git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    _refuse(result.returncode != 0, f"cannot inspect Candidate identity: {result.stderr.strip()}")
    return result.stdout.strip()


def candidate_identity(repo: Path, candidate_root: Path) -> dict[str, str]:
    """Bind a pair to the exact repository/index and unchanged Candidate runtime."""
    repo, candidate_root = repo.resolve(), candidate_root.resolve()
    _refuse(repo != candidate_root, "Candidate root must be the declared repository root")
    _refuse(Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo, "Candidate repository mismatch")
    runtime = "skills/watch"
    _refuse(bool(_git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--", runtime)),
            "Candidate runtime subtree must be clean (tracked, staged, and untracked files)")
    runtime_paths = [repo / control_harness.CONTROL_SCRIPT, repo / "skills/watch/scripts/config.py",
                     repo / "skills/watch/scripts/download.py", repo / "skills/watch/scripts/frames.py",
                     repo / "skills/watch/scripts/transcribe.py", repo / "skills/watch/scripts/whisper.py"]
    _refuse(any(not path.is_file() for path in runtime_paths), "Candidate runtime pin is incomplete")
    digest = hashlib.sha256()
    for path in runtime_paths:
        digest.update(path.relative_to(repo).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
    # `git write-tree` acquires index.lock, which is intentionally unavailable in the
    # sandbox.  Hash the exact staged index entries instead; it is read-only and pins
    # the same Candidate runtime content for this compatibility invocation.
    index_entries = _git(repo, "ls-files", "-s", "--", runtime)
    return {"candidate_commit": _git(repo, "rev-parse", "HEAD"),
            "candidate_index_sha256": hashlib.sha256(index_entries.encode("utf-8")).hexdigest(),
            "candidate_runtime_sha256": digest.hexdigest()}


def _audit_source() -> str:
    return '''import json, os, shutil, socket, subprocess, time, urllib.request
LOG = os.environ.get("P02_AUDIT_LOG")
ALLOWED = set(json.loads(os.environ.get("P02_ALLOWED_EXECUTABLES", "[]")))
def record(kind, value):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as h: h.write(json.dumps({"event":"audit","kind":kind,"value":str(value),"monotonic_ns":time.monotonic_ns()}, sort_keys=True)+"\\n")
_popen = subprocess.Popen
def audited_popen(args, *a, **kw):
    argv = args if isinstance(args, (list, tuple)) else [args]
    if not argv or not isinstance(argv[0], (str, bytes)) or isinstance(args, str) or kw.get("shell"):
        record("subprocess-refusal", argv); raise RuntimeError("P02 audit refused ambiguous subprocess")
    command = os.fsdecode(argv[0])
    resolved = os.path.realpath(command if os.path.isabs(command) else (shutil.which(command) or ""))
    record("subprocess", {"argv": list(argv), "resolved": resolved})
    if not resolved or resolved not in ALLOWED:
        raise RuntimeError("P02 audit refused executable identity drift: " + command)
    return _popen(args, *a, **kw)
subprocess.Popen = audited_popen
def blocked_connect(self, address):
    record("network", address); raise OSError("P02 audit blocked network")
socket.socket.connect = blocked_connect
def blocked_connect_ex(self, address):
    record("network", address); raise OSError("P02 audit blocked network")
socket.socket.connect_ex = blocked_connect_ex
def blocked_sendto(self, bytes, *address):
    record("network", address); raise OSError("P02 audit blocked network")
socket.socket.sendto = blocked_sendto
def blocked_create_connection(address, *a, **kw):
    record("network", address); raise OSError("P02 audit blocked network")
socket.create_connection = blocked_create_connection
def blocked_urlopen(url, *a, **kw):
    record("network", url); raise OSError("P02 audit blocked network")
urllib.request.urlopen = blocked_urlopen
def blocked_system(command):
    record("subprocess", command); raise RuntimeError("P02 audit refused os.system")
os.system = blocked_system
'''


def _wrapper_source(real: Path, log_path: Path, tool: str, fault_mode: str | None = None,
                    audit_dir: Path | None = None, allowed_executables: tuple[Path, ...] = ()) -> str:
    """A pinned Python wrapper records actual child process boundaries and argv."""
    return f'''#!{sys.executable}
import json, os, subprocess, sys, time
REAL = {str(real)!r}
LOG = {str(log_path)!r}
TOOL = {tool!r}
FAULT = {fault_mode!r}
event = {{"event": "start", "tool": TOOL, "argv": sys.argv[1:], "monotonic_ns": time.monotonic_ns()}}
with open(LOG, "a", encoding="utf-8") as handle: handle.write(json.dumps(event, sort_keys=True) + "\\n")
if TOOL == "ffprobe" and FAULT == "failure" and "-version" not in sys.argv[1:]:
    print("P02_FAILURE:ffprobe", file=sys.stderr); result = type("R", (), {{"returncode": 3}})()
elif TOOL == "ffprobe" and FAULT == "timeout" and "-version" not in sys.argv[1:]:
    time.sleep(60); result = type("R", (), {{"returncode": 124}})()
else:
    env = dict(os.environ)
    if TOOL == "python" and {str(audit_dir)!r}:
        env["PYTHONPATH"] = {str(audit_dir)!r}
        env["P02_AUDIT_LOG"] = LOG
        env["P02_ALLOWED_EXECUTABLES"] = {json.dumps([str(path.resolve()) for path in allowed_executables])!r}
    result = subprocess.run([REAL, *sys.argv[1:]], check=False, env=env)
event["event"] = "end"; event["returncode"] = result.returncode; event["monotonic_ns"] = time.monotonic_ns()
with open(LOG, "a", encoding="utf-8") as handle: handle.write(json.dumps(event, sort_keys=True) + "\\n")
raise SystemExit(result.returncode)
'''


def instrument_case(case: Mapping[str, Any], directory: Path, fault_mode: str | None = None) -> tuple[dict[str, Any], Path]:
    """Return a fully re-pinned P01 case whose real tool calls are observable."""
    observed_case = copy.deepcopy(case)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "process-events.jsonl"
    audit_dir = directory / "audit"; audit_dir.mkdir()
    (audit_dir / "sitecustomize.py").write_text(_audit_source(), encoding="utf-8")
    paths: dict[str, str] = {}
    real_tools = {key: Path(value).resolve() for key, value in observed_case["environment"]["tools"].items()}
    for key, executable in real_tools.items():
        name = "yt-dlp" if key == "yt_dlp" else key
        wrapper = directory / name
        wrapper.write_text(_wrapper_source(executable, log_path, key, fault_mode, audit_dir), encoding="utf-8")
        wrapper.chmod(0o700)
        paths[key] = str(wrapper)
    observed_case["environment"]["tools"] = paths
    # The audited watch process may invoke either a PATH-resolved pinned wrapper
    # or its wrapped immutable executable; no basename-only allowance exists.
    allowed = tuple([Path(value).resolve() for value in paths.values()] + list(real_tools.values()))
    for wrapper in (directory / "python", directory / "ffmpeg", directory / "ffprobe", directory / "yt-dlp"):
        wrapper.write_text(_wrapper_source(real_tools["yt_dlp" if wrapper.name == "yt-dlp" else wrapper.name], log_path,
                                            "yt_dlp" if wrapper.name == "yt-dlp" else wrapper.name,
                                            fault_mode, audit_dir, allowed), encoding="utf-8")
        wrapper.chmod(0o700)
    observed_case["environment"]["tool_versions"] = control_harness.capture_tool_versions(paths)
    observed_case["environment"]["tool_sha256"] = control_harness.capture_tool_sha256(paths)
    return observed_case, log_path


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def observe_calls(path: Path, *, timed_out: bool = False) -> dict[str, Any]:
    """Derive call counts and the watched-script interval from wrapper events."""
    events = _read_events(path)
    starts = [event for event in events if event.get("event") == "start" and event.get("tool") == "python"
              and any(str(argument).endswith(control_harness.CONTROL_SCRIPT) for argument in event.get("argv", []))]
    _refuse(len(starts) != 1, "missing or ambiguous watched-process interval")
    start = starts[0]["monotonic_ns"]
    ends = [event for event in events if event.get("event") == "end" and event.get("tool") == "python"
            and event.get("monotonic_ns", 0) >= start]
    _refuse(not ends and not timed_out, "watched-process end was not observed")
    end = ends[-1]["monotonic_ns"] if ends else max(event.get("monotonic_ns", start) for event in events)
    calls = [event for event in events if event.get("event") in {"start", "audit"} and start <= event.get("monotonic_ns", 0) <= end]
    return {"interval_start_ns": start, "interval_end_ns": end, "payload_wall_ms": (end - start) / 1_000_000,
            "process_calls": len(calls),
            "provider_network_calls": sum(event.get("tool") == "yt_dlp" or event.get("kind") == "network" for event in calls),
            "calls": calls}


def _sanitize_command(command: list[str], roots: tuple[Path, ...]) -> list[str]:
    return [normalize_text(str(part), roots) for part in command]


def _sanitize_calls(calls: list[dict[str, Any]], roots: tuple[Path, ...]) -> list[dict[str, Any]]:
    return [{"tool": call.get("tool", f"audit:{call.get('kind')}"),
             "argv": _sanitize_command(call.get("argv", [call.get("value", "")]), roots),
             "monotonic_ns": call["monotonic_ns"]} for call in calls]


def compare_call_observations(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Process and provider counts are observed invariants, never caller constants."""
    differences: list[str] = []
    if control.get("process_calls") != candidate.get("process_calls"):
        differences.append("process_calls")
    if candidate.get("provider_network_calls", 0) > control.get("provider_network_calls", 0):
        differences.append("provider_network_calls")
    return differences


def _isolated_candidate_environment(case: Mapping[str, Any], receipt_dir: Path) -> tuple[dict[str, str], Path]:
    tools = case["environment"]["tools"]
    # Pin before use and place only known executables on PATH, as P01 does.
    observed = control_harness.capture_tool_sha256(tools)
    _refuse(observed != case["environment"]["tool_sha256"], "candidate tool pin drift")
    shims = receipt_dir / "pinned-tools"
    shims.mkdir()
    for name, executable in (("ffmpeg", tools["ffmpeg"]), ("ffprobe", tools["ffprobe"]), ("yt-dlp", tools["yt_dlp"])):
        (shims / name).symlink_to(executable)
    home = receipt_dir / "isolated-home"
    home.mkdir(mode=0o700)
    env = control_harness._isolated_environment(home, f"{shims}{os.pathsep}/usr/bin{os.pathsep}/bin")
    env.update({"LC_ALL": case["environment"]["locale"], "LANG": case["environment"]["locale"], "PYTHONDONTWRITEBYTECODE": "1"})
    return env, shims


def _candidate_command(case: Mapping[str, Any], candidate_root: Path, out_dir: Path) -> list[str]:
    script = candidate_root / control_harness.CONTROL_SCRIPT
    _refuse(not script.is_file(), "Candidate compatibility script is missing")
    return control_harness._build_command(case, {name: Path(value) for name, value in case["environment"]["tools"].items()}, out_dir)[:1] + [str(script)] + control_harness._build_command(case, {name: Path(value) for name, value in case["environment"]["tools"].items()}, out_dir)[2:]


def _run_candidate(case: dict[str, Any], candidate_root: Path, out_dir: Path, receipt_dir: Path) -> dict[str, Any]:
    _refuse(out_dir.exists() and any(out_dir.iterdir()), "Candidate output directory must be empty")
    _refuse(receipt_dir.exists() and any(receipt_dir.iterdir()), "Candidate receipt directory must be empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    env, _ = _isolated_candidate_environment(case, receipt_dir)
    command = _candidate_command(case, candidate_root.resolve(), out_dir.resolve())
    started = time.perf_counter_ns()
    code, stdout, stderr, timed_out = control_harness._run_in_process_group(
        command, candidate_root, env, case["environment"]["timeout_seconds"])
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000
    (receipt_dir / "stdout.raw").write_bytes(stdout)
    (receipt_dir / "stderr.raw").write_bytes(stderr)
    receipt = {"command": command, "exit_code": code, "timed_out": timed_out, "wall_ms": wall_ms,
               "raw_stdout": "stdout.raw", "raw_stderr": "stderr.raw", "raw_output_manifest": _manifest(out_dir)}
    (receipt_dir / "run.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def latency_allowance_ms(noop_ms: list[float], control_wall_ms: float) -> float:
    _refuse(len(noop_ms) < 3, "missing deterministic no-op measurements")
    ordered = sorted(noop_ms)
    p50 = statistics.median(ordered)
    p95 = ordered[(95 * len(ordered) + 99) // 100 - 1]
    return max(5.0, 0.05 * control_wall_ms, p95 - p50)


def _noop_measurements(python: str, cwd: Path, environment: Mapping[str, str], count: int = 3) -> list[float]:
    """Measure the same pinned Python wrapper used for each arm's payload."""
    values = []
    for _ in range(count):
        start = time.perf_counter_ns()
        result = subprocess.run([python, "-c", "pass"], cwd=cwd, env=dict(environment), check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _refuse(result.returncode != 0, "no-op measurement failed")
        values.append((time.perf_counter_ns() - start) / 1_000_000)
    return values


def run_pair(case: dict[str, Any], *, repo: Path, control_worktree: Path, candidate_root: Path,
             artifact_root: Path, allowed_differences: frozenset[str] = frozenset({"temporary_paths"}),
             fault_mode: str | None = None) -> dict[str, Any]:
    """Run the paired arms in P01 order and reject every invalid comparison."""
    _refuse(not allowed_differences.issubset(ALLOWED_DIFFERENCES), "undeclared allowed difference")
    control_harness.validate_case(case)
    control_harness.assert_clean_detached_control(control_worktree, control_harness.CONTROL_COMMIT)
    _refuse(not candidate_root.is_dir() or not repo.is_dir(), "missing paired repository root")
    identity = candidate_identity(repo, candidate_root)
    _refuse(artifact_root.exists() and any(artifact_root.iterdir()), "pair artifact directory must be empty")
    artifact_root.mkdir(parents=True)
    order = paired_order(case["case_id"])
    receipts: dict[str, dict[str, Any]] = {}
    receipt_paths: dict[str, Path] = {}
    summaries: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    noops: dict[str, list[float]] = {}
    for arm in order:
        arm_root = artifact_root / arm
        out, receipt = arm_root / "out", arm_root / "receipt"
        receipt_paths[arm] = receipt
        arm_root.mkdir()
        arm_case, event_log = instrument_case(case, arm_root / "observer", fault_mode)
        if arm == "control":
            # P01 validates the pinned observer wrappers before invoking the unchanged Control.
            noop_home = arm_root / "noop-home"; noop_home.mkdir()
            noop_env = control_harness._isolated_environment(noop_home, "/usr/bin:/bin")
            noops[arm] = _noop_measurements(arm_case["environment"]["tools"]["python"], control_worktree, noop_env)
            receipts[arm] = control_harness.run_control(arm_case, control_worktree, out, receipt)
        else:
            noop_home = arm_root / "noop-home"; noop_home.mkdir()
            noop_env = control_harness._isolated_environment(noop_home, "/usr/bin:/bin")
            noops[arm] = _noop_measurements(arm_case["environment"]["tools"]["python"], candidate_root, noop_env)
            receipts[arm] = _run_candidate(arm_case, candidate_root, out, receipt)
        observations[arm] = observe_calls(event_log, timed_out=receipts[arm]["timed_out"])
        stdout = (receipt / "stdout.raw").read_text(encoding="utf-8", errors="replace")
        stderr = (receipt / "stderr.raw").read_text(encoding="utf-8", errors="replace")
        summaries[arm] = summarize_output(out, stdout, stderr, (artifact_root.parent, Path(case["source"]).parent,
                                                                  candidate_root, control_worktree))
        summaries[arm]["outcome"] = derive_outcome(receipts[arm]["exit_code"], receipts[arm]["timed_out"], stdout, stderr)
        summaries[arm]["exit_class"] = summaries[arm]["outcome"]["exit_class"]
    outcome_differences = compare_outcomes(summaries["control"]["outcome"], summaries["candidate"]["outcome"])
    _refuse(bool(outcome_differences), f"unexplained outcome difference: {', '.join(outcome_differences)}")
    differences = compare_summaries(summaries["control"], summaries["candidate"], allowed=allowed_differences)
    _refuse(bool(differences), f"unexplained behavioral difference: {', '.join(differences)}")
    call_differences = compare_call_observations(observations["control"], observations["candidate"])
    _refuse(bool(call_differences), f"unexplained process/provider difference: {', '.join(call_differences)}")
    allowance = latency_allowance_ms(noops["control"], observations["control"]["payload_wall_ms"])
    if summaries["control"]["exit_class"] == "success":
        _refuse(observations["candidate"]["payload_wall_ms"] > observations["control"]["payload_wall_ms"] + allowance,
                "Candidate latency exceeds declared deterministic allowance")
    control_harness.assert_clean_detached_control(control_worktree, control_harness.CONTROL_COMMIT)
    roots = (artifact_root.parent, Path(case["source"]).parent, candidate_root, control_worktree,
             *(Path(value).resolve().parent for value in case["environment"]["tools"].values()))
    result = {"schema_version": 1, "case_id": case["case_id"], "paired_order": list(order),
              "routing_version": ROUTING_VERSION, "control_commit": control_harness.CONTROL_COMMIT,
              "candidate": identity, "retry_policy": case["environment"]["invocation_policy"],
              "allowed_differences": sorted(allowed_differences), "latency_allowance_ms": allowance,
              "no_op_samples_ms": noops,
              "arms": {arm: {**summaries[arm]["outcome"], "payload_wall_ms": observations[arm]["payload_wall_ms"],
                              "raw_manifest": summaries[arm]["raw_manifest"], "frames": summaries[arm]["frames"],
                              "transcript": summaries[arm]["transcript"], "provider_network_calls": observations[arm]["provider_network_calls"],
                              "process_calls": observations[arm]["process_calls"], "command": _sanitize_command(receipts[arm]["command"], roots),
                              "stdout": summaries[arm]["stdout"], "stderr": summaries[arm]["stderr"],
                              **raw_receipt_hashes(receipt_paths[arm]),
                              "observed_calls": _sanitize_calls(observations[arm]["calls"], roots)} for arm in ("control", "candidate")}}
    (artifact_root / "conformance.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def run_evidence_fallback(source: Path, *, candidate_root: Path, out_dir: Path, question: str,
                          resolution: int = 160, max_frames: int = 4) -> dict[str, Any]:
    """Exercise the real local-source evidence failure and its balanced fallback."""
    script = candidate_root / control_harness.CONTROL_SCRIPT
    _refuse(not source.is_file() or not script.is_file(), "local fixture or Candidate script is missing")
    def invoke(detail: str, path: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, Any], dict[str, Any]]:
        observer = out_dir / "observer" / detail
        log = observer / "process-events.jsonl"
        tools = {"python": sys.executable, "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
                 "yt_dlp": shutil.which("yt-dlp")}
        _refuse(any(not isinstance(value, str) or not Path(value).is_file() for value in tools.values()),
                "fallback observer tool is unavailable")
        observer.mkdir(parents=True, exist_ok=True)
        audit_dir = observer / "audit"; audit_dir.mkdir()
        (audit_dir / "sitecustomize.py").write_text(_audit_source(), encoding="utf-8")
        real_tools = {key: Path(value).resolve() for key, value in tools.items()}
        wrapped: dict[str, str] = {}
        for key in tools:
            wrapper = observer / ("yt-dlp" if key == "yt_dlp" else key)
            wrapped[key] = str(wrapper)
        allowed = tuple([Path(value).resolve() for value in wrapped.values()] + list(real_tools.values()))
        for key, wrapper_text in wrapped.items():
            wrapper = Path(wrapper_text)
            wrapper.write_text(_wrapper_source(real_tools[key], log, key, audit_dir=audit_dir,
                                                allowed_executables=allowed), encoding="utf-8")
            wrapper.chmod(0o700)
        home = observer / "home"; home.mkdir()
        env = control_harness._isolated_environment(home, f"{observer}{os.pathsep}/usr/bin{os.pathsep}/bin")
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "WATCH_DETAIL": "balanced"})
        proc = subprocess.run([wrapped["python"], str(script), str(source), "--detail", detail, "--question", question,
                               "--no-whisper", "--resolution", str(resolution), "--max-frames", str(max_frames), "--out-dir", str(path)],
                              cwd=candidate_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                              env=env)
        return proc, summarize_output(path, proc.stdout, proc.stderr, (out_dir, source.parent, candidate_root)), observe_calls(log)
    evidence, evidence_summary, evidence_calls = invoke("evidence", out_dir / "evidence")
    balanced, balanced_summary, balanced_calls = invoke("balanced", out_dir / "balanced")
    warning = "[watch] evidence mode failed"
    _refuse(evidence.returncode != 0 or balanced.returncode != 0, "evidence fallback did not produce usable result")
    _refuse(evidence.stderr.count(warning) != 1, "evidence fallback must emit exactly one documented warning")
    _refuse("falling back to balanced" not in evidence.stderr, "evidence fallback warning lacks disposition")
    _refuse(compare_summaries(balanced_summary, evidence_summary,
                               allowed=frozenset({"temporary_paths", "evidence_fallback_warning"})) != [],
            "evidence fallback does not normalize to balanced")
    _refuse(evidence_calls["provider_network_calls"] > balanced_calls["provider_network_calls"],
            "evidence fallback made an extra provider/network call")
    fallback_tool_roots = (Path(sys.executable).resolve().parent,
                           Path(shutil.which("ffmpeg") or "/nonexistent").resolve().parent,
                           Path(shutil.which("ffprobe") or "/nonexistent").resolve().parent,
                           Path(shutil.which("yt-dlp") or "/nonexistent").resolve().parent)
    roots = (out_dir, source.parent, candidate_root, *fallback_tool_roots)
    for calls in (evidence_calls, balanced_calls):
        calls["calls"] = _sanitize_calls(calls["calls"], roots)
    return {"evidence_exit": evidence.returncode, "balanced_exit": balanced.returncode,
            "warning_count": evidence.stderr.count(warning), "fallback_order": ["evidence", "balanced"],
            "evidence_calls": evidence_calls,
            "balanced_calls": balanced_calls, "balanced": balanced_summary, "evidence": evidence_summary}


def _fixture_outcome(code: int, timed_out: bool, stderr: str) -> dict[str, Any]:
    fallback = re.findall(r"P02_FALLBACK:([a-z0-9_-]+)", stderr)
    failure = re.search(r"P02_FAILURE:([a-z0-9_-]+)", stderr)
    return {"exit_class": "timeout" if timed_out else "success" if code == 0 else "failure",
            "failure_class": "timeout" if timed_out else failure.group(1) if failure else None if code == 0 else "runtime_error",
            "fallback_order": fallback}


def compare_outcomes(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Conformance primitive used by real runs and deterministic failure fixtures."""
    fields = ("exit_class", "failure_class", "fallback_order")
    return [field for field in fields if control.get(field) != candidate.get(field)]


def run_deterministic_fixture_pair(kind: str, root: Path, *, candidate_kind: str | None = None) -> dict[str, Any]:
    """Exercise success, categorized failure, timeout cleanup, and fallback order.

    These are harness fixtures, not alternate Control commands.  Their commands are generated
    internally from a closed behavior set, so callers cannot smuggle arbitrary invocation.
    """
    _refuse(kind not in {"success", "failure", "timeout", "fallback"}, "unknown deterministic fixture")
    candidate_kind = candidate_kind or kind
    _refuse(candidate_kind not in {"success", "failure", "timeout", "fallback"}, "unknown deterministic fixture")
    _refuse(root.exists() and any(root.iterdir()), "fixture root must be empty")
    root.mkdir(parents=True)
    def command(behavior: str) -> list[str]:
        if behavior == "timeout":
            source = "import time; time.sleep(60)"
        elif behavior == "failure":
            source = "import sys; print('P02_FAILURE:invalid_source', file=sys.stderr); raise SystemExit(3)"
        elif behavior == "fallback":
            source = "import sys; print('P02_FALLBACK:native', file=sys.stderr); print('P02_FALLBACK:sidecar', file=sys.stderr)"
        else:
            source = "print('P02_SUCCESS')"
        return [sys.executable, "-c", source]
    result: dict[str, Any] = {"kind": kind, "arms": {}}
    for arm, behavior in (("control", kind), ("candidate", candidate_kind)):
        started = time.perf_counter_ns()
        code, stdout, stderr, timed_out = control_harness._run_in_process_group(command(behavior), root, os.environ.copy(), 1)
        result["arms"][arm] = {**_fixture_outcome(code, timed_out, stderr.decode("utf-8", errors="replace")),
                               "stdout": stdout.decode("utf-8", errors="replace"),
                               "stderr": stderr.decode("utf-8", errors="replace"),
                               "wall_ms": (time.perf_counter_ns() - started) / 1_000_000}
    differences = compare_outcomes(result["arms"]["control"], result["arms"]["candidate"])
    result["differences"] = differences
    _refuse(bool(differences), f"fixture behavioral difference: {', '.join(differences)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route", help="route a pre-outcome request JSON document")
    route.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.request.read_text(encoding="utf-8"))
        _refuse(not isinstance(payload, dict) or set(payload) - {"question", "explicit_detail", "timestamps", "mirrored_flags", "source_metadata"},
                "routing document contains outcome-derived input")
        print(json.dumps(route_control(RoutingRequest(**payload)), sort_keys=True))
    except (OSError, json.JSONDecodeError, TypeError, ConformanceRefusal) as exc:
        print(f"control-conformance: integrity refusal: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
