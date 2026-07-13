# v1.0 status in plain language

Last updated: 2026-07-12

[`claude-video-plus 1.0.3`](https://github.com/abe238/claude-video-plus/releases/latest)
is the current stable public release. It is ready to install and use. Current engineering evidence:

- 338 local deterministic tests pass;
- all five hosted macOS/Linux Python 3.11–3.14 jobs pass;
- all four advertised install paths pass in isolation: Claude Code marketplace plugin,
  `npx skills` (install, diagnostics, uninstall, source preservation), the release
  `watch.skill` artifact, and the manual clone-and-symlink path;
- the v1.0.3 release ships a deterministic `watch.skill` of 82,838 bytes with SHA-256
  `51f35fd113e4922368d19735a29c6eee0ce2e507844891d7452943ec8f1b081d`;
- the independent blocker re-review returned `APPROVE_EARLY_PUBLISH` for commit `c0efe18`.

The release includes a self-contained [`watch.skill`](https://github.com/abe238/claude-video-plus/releases/latest/download/watch.skill)
and the repository supports the same one-command Agent Skills install used by the original.

## The research program is complete

Every check on the original measurement plan has now run. Nothing remains open:

- the multi-video development battery ran and is published unedited, wins and losses
  ([battery](benchmarks/2026-07-12-multi-video-battery/));
- the answer grader was validated for repeatability (max 1-point drift), the answer keys
  were frozen by two independent model annotators before any pipeline ran, and blinding
  was hardened after an adversarial leak probe
  ([confirmatory raw data](benchmarks/2026-07-12-confirmatory/));
- the sealed confirmation set was opened exactly once under the receipt gate and the
  frozen candidate evaluated: **quality parity (8.83 vs 8.80) with identical gold-fact
  coverage at a 56% mean token reduction**: 3 wins, 4 ties, 3 losses
  ([sealed run](benchmarks/2026-07-12-confirmatory/));
- cold end-to-end timing (evidence mode ~14 s faster than the balanced default) and the
  whole-project reliability record are published
  ([performance](benchmarks/2026-07-12-performance/));
- the one negative result (the OpenCV frame scorer) is published with raw data and the
  mechanism was rejected ([ablation](benchmarks/2026-07-11-opencv-ablation/)).

The full evidence index is [docs/benchmarks/](benchmarks/).

## What shipped

All 33 requirement slices (P00–P32) are implemented, measured, and released:
the strict comparison harness against the untouched original; consistent download,
retry, and caption handling; local-first transcription (sidecar subtitles, optional
localhost endpoint, detected YAP, explicit cloud Whisper); range extraction and safe
evidence reuse; question-aware retrieval with the numeric guard and chronology
preservation; and the evidence-mode frame selection the benchmarks measure. Videos
under 9 minutes and any internal error route to the original pipeline automatically.

The plain-language specification of each slice lives in the
[issue tracker](https://github.com/abe238/claude-video-plus/issues?q=is%3Aissue); the
machine-readable registry is
[`docs/execution/v1/REQUIREMENTS.json`](execution/v1/REQUIREMENTS.json); the full design
and measurement rules live in [`V1.0-MASTER-PLAN.md`](plans/V1.0-MASTER-PLAN.md); the
source-by-source design provenance is
[`PROVENANCE.md`](execution/v1/PROVENANCE.md). This page is the human-readable view; if
it ever disagrees with the registry, the registry wins.

## What "done" meant

A packet was complete only after its focused tests and the full suite passed, its live
or benchmark evidence was recorded, an independent Sol review found no unresolved
high-priority issue, the exact reviewed tree was committed and pushed, and the matching
GitHub issue was closed. A code commit by itself was never completion, and no
development result became a public performance claim before the sealed confirmation
gate, which has now run, once, with the receipt published.
