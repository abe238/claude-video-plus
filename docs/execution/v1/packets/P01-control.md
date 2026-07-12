# P01 — Frozen Control harness

## Frozen inputs

- Master-plan commit: `edc2ce6696a88501f19060cc2000ed4f513c6133`
- Requirement: `CTRL-001`
- GitHub issue: `#1`
- Frozen Control commit: `83da59fa78c3eee9e20f515fe75c438bb5166efd`

## Observable outcome

`tools/control_harness.py` can create or validate a detached, clean worktree at the
frozen Control commit, and can run its fixed `watch.py` command only from a complete,
version-pinned case record. It writes output, raw stdout/stderr, and a receipt outside
the Control worktree.

## Ownership

Owned new paths: `tools/control_harness.py`, `tests/test_control_harness.py`,
`docs/execution/v1/packets/P01-control.md`, and `docs/evidence/v1/P01-control/`.

Off limits: all existing runtime files, `REQUIREMENTS.json`, master-plan documents,
and P00 evidence.

## Required behavior and refusal behavior

- The checkout must be detached, exactly at the frozen SHA, and have empty porcelain
  status both before and after execution. Any mismatch is an integrity refusal (exit 4).
- The harness builds the invocation itself: `PINNED_PYTHON
  skills/watch/scripts/watch.py SOURCE [frozen flags] --out-dir CONTROL_OUT`.
  It accepts no caller-supplied executable command or shell string.
- Every case pins a source kind consistent with either a local path or an HTTP(S) URL,
  the local-source or exact-URL identity hash, and an expected selected-caption SHA-256
  (or explicit null), Question, all supported upstream flags, Python/FFmpeg/
  ffprobe/yt-dlp executable paths, exact version lines, and executable SHA-256 values,
  OS/architecture/locale,
  network/cookie-input policy, timeout, one harness invocation, and reader prompt/model epoch.
  Missing, changed, or unsupported provenance is an integrity refusal before execution.
- A caption path or undeclared provenance field is never supplied as an unrelated sidecar input.
  The pinned yt-dlp executable is invoked through a hash-recorded pass-through wrapper that
  snapshots every VTT immediately after each yt-dlp call, before frozen Control resumes. The
  harness applies frozen `download._pick_subtitle` and VTT cue rules to those chronological
  snapshots and compares the exact consumed VTT bytes with the expected hash. Local
  Control is required to expect no consumed caption; URL cases may expect either one selected
  caption or no selected caption. The receipt records the expected and selected identities.
- The subprocess receives a minimal allowlisted environment: only the isolated empty
  home/config/cache, locale, bytecode suppression, and a `PATH` containing the pinned tool
  shims followed by `/usr/bin:/bin` are present. The shims are necessary because unchanged
  upstream invokes `ffmpeg`, `ffprobe`, and `yt-dlp` by name; the system paths remain for the
  Python runtime and ordinary OS utilities.
  It inherits neither Python path/home overrides nor arbitrary secrets, and disables bytecode
  emission so Control cannot create ignored runtime files. Every Git command is similarly run
  with a scrubbed Git environment and isolated home. Whisper is explicitly disabled until a
  later packet defines a secret-safe, reproducible pin.
- The frozen policy is one invocation of the unchanged upstream command, with a pinned yt-dlp
  executable/version, isolated HOME/config, and no harness cookie input. P01 does **not** claim
  to disable or alter upstream/yt-dlp internal retry or cookie defaults; those remain exactly
  the behavior of commit `83da59f` under that isolated environment.
- `source_identity` and `invocation_policy` reject every undeclared field; receipts therefore
  cannot preserve unenforced sidecar, retry, or cookie claims as if they were guarantees.
- Paired Control/Candidate position is the SHA-256 parity of `case_id`; the receipt
  preserves the deterministic order for P02 to use. P01 invokes only the Control arm.
- Output and receipt directories must be empty, external, and neither equal nor ancestors or
  descendants of one another after resolution.
  Raw stdout/stderr and a hash manifest of the unmodified output tree are preserved.

## Tests and proof

- `tests/test_control_harness.py` covers detached-worktree preparation; tracked and ignored
  dirty-tree refusals; source/caption kind and byte-drift checks; path/version/content executable
  pins before probes; minimal-environment and Git-environment isolation; equal/overlapping
  output/receipt paths; process-group timeout cleanup including resistant descendants;
  deterministic paired order; a local
  fixture Control run; and raw-output receipt preservation.
- The provisional evidence directory also records a network-free live run of the actual frozen
  Control against generated local media. It is a harness proof, not a network-acquisition or
  performance benchmark.

## Deterministic verification

```text
python3 -m pytest -q tests/test_control_harness.py
python3 -m pytest -q
python3 -m compileall -q skills tools tests
python3 tools/validate_v1_execution.py
python3 tools/validate_v1_evidence.py docs/evidence/v1/P01-control/verify.json
git diff --check
```

## Evidence and bounds

P01 writes provisional implementation evidence under `docs/evidence/v1/P01-control/`.
Sol must review the exact staged tree and these receipts before the packet can close.
At most two valid PROVE failures and three review/fix rounds are permitted. Stop for a
request to alter Control, to run with unpinned tools/provenance, or to expand into
Candidate conformance/routing (P02).
