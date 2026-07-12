# Luna development readiness — Pass 1

Date: 2026-07-12

Scope: development-only readiness and deterministic checks. No confirmatory cohort was opened,
listed beyond registry split counts, hashed as media, or run. No runtime, existing evidence,
commit, tag, or push was changed.

## Corpus and binding checks

Command: `python3 tools/corpus_registry.py docs/execution/v1/CORPUS-REGISTRY-v1.json`

Exit: `0`

Result: registry seal and structure valid. The registry has 2 development families and 5
confirmatory families; the frozen candidate commit/config and supported class/environment bindings
are present. The authorized development view returned only
`dev-source-placeholder-001` and `dev-source-placeholder-002`.

The two development identities are SHA-256-shaped opaque placeholder labels. The registry
contains no URL, path, media bytes, caption, or other source locator. Therefore there are no real
development sources to hash or execute, and no candidate/control case bindings to run. The registry
also declares `mechanical:synthetic-placeholder-unavailable` as an exclusion.

## Tool availability

Observed executable paths:

- Python: `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`, version 3.14.4
- FFmpeg: `/opt/homebrew/bin/ffmpeg`, version 8.1
- ffprobe: `/opt/homebrew/bin/ffprobe`, version 8.1
- yt-dlp: `~/.local/bin/yt-dlp`; its version probe emitted a PyInstaller semaphore
  permission warning and did not produce a version line in this environment.

Tools are present, but availability does not repair the absent development media/case manifest.

## Commands run

| Command | Exit | Compact result |
|---|---:|---|
| `python3 -m pytest -q tests/test_corpus_registry.py tests/test_v1_evaluator.py` | 0 | 31 passed |
| `python3 -m pytest -q tests/test_execution_registry.py` | 1 in Luna sandbox | 1 failed, 15 passed; network-dependent issue lookup unavailable |
| `python3 -m compileall -q skills tools tests` | 0 | completed |
| `python3 tools/validate_v1_execution.py` | 1 in Luna sandbox; 0 in coordinator | Luna could not validate GitHub issue identities; coordinator returned `ok: 45 requirements, 35 packets` |
| `python3 tools/evaluate_v1.py tests/fixtures/v1_evaluator_golden.json` | 0 | deterministic golden fixture evaluated |
| `git diff --check` | 0 | no whitespace errors |

The evaluator fixture is a synthetic unit fixture, not a development benchmark. No fixed
original/candidate video command was runnable: no development source/case manifest or benchmark
runner input exists, and the only registered development sources are placeholders.

## Output-directory readiness

`docs/evidence/v1/P03-measurement/` and its `raw/` directory exist but contain prior evidence;
they are not empty benchmark output directories. They were not cleared or reused. No separate
development benchmark output directory exists. `docs/benchmarks/` exists but contains no runnable
development corpus output.

## Exact blockers

1. The development corpus is unavailable: both registered development identities are synthetic
   placeholders and have no source locators or media bytes.
2. No candidate/control development case manifest and fixed end-to-end benchmark command are
   available to bind those sources.
3. Luna's workspace sandbox could not complete the network-dependent P00/P01 issue checks. This is
   not a repository blocker: the coordinator reran the validator with GitHub access and it passed.
4. Existing P03 evidence output directories are non-empty; clearing or modifying them is outside
   this pass.

## Smallest next action

Provide or register the real development source identities and case manifest (including exact
Control/Candidate bindings and output locations), then rerun the fixed development-only commands.
Execution-registry validation is green in the coordinator environment. Until the source manifest
exists, stop without inventing sources or running a benchmark.
