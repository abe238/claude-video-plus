# v1.0 status in plain language

Last updated: 2026-07-12

[`claude-video-plus 1.0.1`](https://github.com/abe238/claude-video-plus/releases/tag/v1.0.1)
is the current stable public release. It is ready to install and use. Current engineering evidence:

- 337 local deterministic tests pass;
- all five hosted macOS/Linux Python 3.11–3.14 jobs pass;
- isolated `npx skills` install, diagnostics invocation, uninstall, and source-preservation pass;
- deterministic `watch.skill` is 82,560 bytes with SHA-256
  `225da27bdc9887e35e61dd0230f957ebfbb4fe2663f2c39ff813137fe58a7338`;
- the independent blocker re-review returned `APPROVE_EARLY_PUBLISH` for commit `c0efe18`.

The release includes a self-contained [`watch.skill`](https://github.com/abe238/claude-video-plus/releases/download/v1.0.1/watch.skill)
and the repository supports the same one-command Agent Skills install used by the original.

The following research remains open, but does not block using stable v1.0:

- run the multi-video development benchmarks and publish Pareto evidence;
- validate the grader, open the sealed confirmation set once, and evaluate the frozen Candidate;
- complete the final claim audit before making any broad superiority claim.

The machine-readable source of truth is
[`docs/execution/v1/REQUIREMENTS.json`](execution/v1/REQUIREMENTS.json). The full design and
measurement rules live in [`V1.0-MASTER-PLAN.md`](plans/V1.0-MASTER-PLAN.md). This page is the
human-readable view; if it ever disagrees with the registry, the registry wins.

The implementation for P02–P32 is assembled. Remaining work is consolidated measurement for
stronger comparative claims—not more feature-building loops. The economical sequence is documented
in [`V1.0-LOW-COST-COMPLETION.md`](plans/V1.0-LOW-COST-COMPLETION.md).

## Implemented foundations

| Step | What it means | Evidence |
| --- | --- | --- |
| P00 | The owner-approved plan, requirements, test rules, and independent-review process are frozen. | [Issue #3](https://github.com/abe238/claude-video-plus/issues/3) · [plan evidence](evidence/v1/L0-plan-review/) |
| P01 | The untouched original version has a strict comparison harness that pins sources, captions, tools, settings, raw output, and failures. | [Issue #1](https://github.com/abe238/claude-video-plus/issues/1) · [Control evidence](evidence/v1/P01-control/) |

P02–P32 implementation is present as integrated runtime/tooling slices. Their issues remain open
until the consolidated verification phase supplies passing evidence and final review.

## Next research: prove broader comparisons

| Step | What remains | Issue |
| --- | --- | --- |
| P02 | Prove the new skill's compatibility backup behaves like the untouched original, and choose the cheapest fair original mode before seeing outcomes. | [#4](https://github.com/abe238/claude-video-plus/issues/4) |
| P03 | Seal the raw evidence formats, scoring program, timing/jitter rules, and separate development versus confirmation video families. | [#5](https://github.com/abe238/claude-video-plus/issues/5) |

## Release and installation basics

| Step | What remains | Issue |
| --- | --- | --- |
| P04 | Keep versions, public claims, release notes, credits, and repository metadata consistent. | [#6](https://github.com/abe238/claude-video-plus/issues/6) |
| P05 | Prove the downloadable skill contains only the intended runtime files and remains small. | [#7](https://github.com/abe238/claude-video-plus/issues/7) |
| P06 | Test install, update, invocation, rollback, cleanup, and uninstall on every advertised platform. | [#8](https://github.com/abe238/claude-video-plus/issues/8) |

## More reliable video and caption fetching

| Step | What remains | Issue |
| --- | --- | --- |
| P07 | Give every download attempt one consistent success/failure result and understandable failure category. | [#9](https://github.com/abe238/claude-video-plus/issues/9) |
| P08 | Add a bounded YouTube retry ladder without slowing ordinary successful downloads. | [#10](https://github.com/abe238/claude-video-plus/issues/10) |
| P09 | Support optional browser cookies without exposing cookie values or profile details. | [#11](https://github.com/abe238/claude-video-plus/issues/11) |
| P10 | Improve caption language selection and rate-limit fallbacks; keep Fathom outside v1.0. | [#12](https://github.com/abe238/claude-video-plus/issues/12) |

## Local-first transcription

| Step | What remains | Issue |
| --- | --- | --- |
| P11 | Make captions and every speech-to-text backend return one consistent timestamped result. | [#13](https://github.com/abe238/claude-video-plus/issues/13) |
| P12 | Use same-name local VTT/SRT subtitle files before any speech-to-text work. | [#14](https://github.com/abe238/claude-video-plus/issues/14) |
| P13 | Add the optional localhost OpenAI-compatible transcription endpoint, including port `8082`, without probing remote servers automatically. | [#15](https://github.com/abe238/claude-video-plus/issues/15) |
| P14 | Detect optional YAP transcription on supported Macs without installing it automatically. | [#16](https://github.com/abe238/claude-video-plus/issues/16) |
| P15 | Put Groq/OpenAI Whisper behind the same bounded, explicit, privacy-aware interface. | [#17](https://github.com/abe238/claude-video-plus/issues/17) |
| P16 | Make options and machine-readable diagnostics behave consistently across Claude, Codex, Cursor, Copilot, and other hosts. | [#18](https://github.com/abe238/claude-video-plus/issues/18) |

## Process less work and safely reuse it

| Step | What remains | Issue |
| --- | --- | --- |
| P17 | Extract and transcribe only requested time ranges, then restore timestamps to the original video clock. | [#19](https://github.com/abe238/claude-video-plus/issues/19) |
| P18 | Split audio near silence and keep receipts so successful chunks do not need to run again. | [#20](https://github.com/abe238/claude-video-plus/issues/20) |
| P19 | Add private, atomic, size-limited evidence storage with verification and purge controls. | [#21](https://github.com/abe238/claude-video-plus/issues/21) |
| P20 | Export, verify, and replay portable evidence bundles without silently including private media. | [#22](https://github.com/abe238/claude-video-plus/issues/22) |
| P21 | Transport the complete user question safely and preserve a reliable compatibility fallback. | [#23](https://github.com/abe238/claude-video-plus/issues/23) |
| P21A | Start with cheap evidence and expand only within a fixed budget when the answer is not yet supported. | [#24](https://github.com/abe238/claude-video-plus/issues/24) |
| P21B | Reuse low-cost video scouting across follow-up questions without changing reader behavior unexpectedly. | [#25](https://github.com/abe238/claude-video-plus/issues/25) |

## Understand meaning while preserving exact facts

| Step | What remains | Issue |
| --- | --- | --- |
| P22 | Strengthen word-based retrieval and protect exact numbers, names, negations, and requested facts. | [#26](https://github.com/abe238/claude-video-plus/issues/26) |
| P23 | Preserve chronological and before/after evidence when the question requires coverage over time. | [#27](https://github.com/abe238/claude-video-plus/issues/27) |
| P24 | Build a frozen test set for paraphrases, cross-language questions, and cases that truly need semantic search. | [#28](https://github.com/abe238/claude-video-plus/issues/28) |
| P25 | Evaluate an optional local semantic-search adapter and its complete installation/runtime cost. | [#29](https://github.com/abe238/claude-video-plus/issues/29) |
| P26 | Evaluate an explicitly authorized remote semantic option, counting transmitted data, tokens, money, and time. | [#30](https://github.com/abe238/claude-video-plus/issues/30) |
| P27 | Evaluate understandable score fusion and OCR; keep only mechanisms that improve final answers. | [#31](https://github.com/abe238/claude-video-plus/issues/31) |

## Better visual evidence selection

| Step | What remains | Issue |
| --- | --- | --- |
| P28 | Test dependency-free FFmpeg/standard-Python signals for important screen changes against answer quality, duplicates, tokens, and total runtime. | [#32](https://github.com/abe238/claude-video-plus/issues/32) |

## Optional confirmation campaign after v1.0

| Step | What remains | Issue |
| --- | --- | --- |
| P29 | Verify the untouched confirmation set is still sealed, then open it only with the required authorization. | [#33](https://github.com/abe238/claude-video-plus/issues/33) |
| P30 | Validate the answer grader against human judgments and freeze exactly one release candidate. | [#34](https://github.com/abe238/claude-video-plus/issues/34) |
| P31 | Run the confirmation evaluation once and publish complete raw results, including failures. | [#35](https://github.com/abe238/claude-video-plus/issues/35) |
| P32 | Audit the install surfaces, evidence, attribution, limits, rollback, and release artifact; then maintain stable releases. | [#36](https://github.com/abe238/claude-video-plus/issues/36) |

## What “done” means

A packet is complete only after its focused tests and the full suite pass, its live or benchmark
evidence is recorded, an independent Sol review finds no unresolved high-priority issue, the
exact reviewed tree is committed and pushed, and the matching GitHub issue is closed. A code
commit by itself is not completion, and a development result cannot become a broad performance
claim before the final confirmation gate.
