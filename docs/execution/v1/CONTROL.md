# Control and comparison contract

## Three distinct concepts

1. **Frozen experimental Control:** an untouched checkout of upstream commit `83da59f`.
   It is the only implementation called Control in benchmark results.
2. **Candidate compatibility fallback:** code inside the Candidate that reproduces the
   supported upstream modes when query-aware behavior is disabled or fails. It is never
   accepted as proof of Control performance; it must pass conformance against the frozen
   checkout.
3. **Cheapest applicable Control mode:** a preregistered rule selecting a frozen-Control
   invocation from user-visible inputs before outcomes are observed.

Every comparison record must name all three where applicable and include the Control commit,
Candidate commit/configuration, selected routing-rule version, commands, environment, retry
policy, raw manifests, and failures.

## Frozen-Control execution

Create a detached clean worktree at `83da59f`. Never patch it. Record `git status --porcelain`
as empty before and after a run. Invoke:

```text
python3 skills/watch/scripts/watch.py SOURCE [frozen flags] --out-dir CONTROL_OUT
```

Pin Python, FFmpeg, ffprobe, yt-dlp, OS/architecture, locale, network policy, source identity,
caption files, cookies policy, timeout, retries, Question, and reader prompt/model epoch in the
case record. Control and Candidate run in alternating paired order determined from the case ID
hash, with separate empty output directories and equivalent warm/cold state.

## Cheapest-control routing v1

Evaluate the first matching rule using only the Question, explicit user flags/hints, and source
metadata available before media analysis:

| Priority | Input condition | Frozen-Control invocation |
| ---: | --- | --- |
| 1 | User explicitly selected a supported detail mode | that exact mode and explicit flags |
| 2 | User supplied `--timestamps` | `transcript` plus those timestamps |
| 3 | Question explicitly asks about visible UI, text, table, object, motion, transition, or before/after state | `balanced` |
| 4 | Question requests coverage, summary, all topics, or chronology | `balanced` |
| 5 | Question asks only what was said/explained and contains no visual requirement | `transcript` |
| 6 | Any other question or no Question | `balanced` |

Explicit `--start`, `--end`, resolution, frame budget, Whisper, and dedup flags are mirrored in
both arms. Gold labels, transcript contents, chapter contents, selected Evidence spans, and
observed results may not influence routing. Any routing change creates a new version and cannot
be applied retroactively to a confirmatory cohort.

## Candidate-fallback conformance

Conformance is behavioral, not byte-for-byte. On deterministic local fixtures, compare frozen
Control with the Candidate fallback for:

- exit class and stdout/stderr contract;
- selected mode and effective arguments;
- transcript segments/timestamps after canonical normalization;
- frame count, requested cue timestamps, dimensions, and deterministic ordering;
- fallback order and categorized failure result;
- no additional network or provider call;
- default-path latency within the frozen jitter allowance.

Allowed differences are temporary paths, manifest-only provenance, and explicitly documented
bug/security fixes. Each allowed difference needs a fixture and disposition. An unexplained
difference blocks the packet.
