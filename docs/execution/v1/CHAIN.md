# v1.0 Cascade chain

Date: 2026-07-11

Pacing: **autonomous and single-pass** for P02 through P32, with mandatory stops only for genuine
external blockers, material scope expansion, and the final public-release gate.

Source: `docs/plans/V1.0-MASTER-PLAN.md` at the commit recorded in
`REQUIREMENTS.json`. The upstream control remains commit `83da59f`.

## Loop anatomy

Each loop has one goal, a self-contained prompt, checkable acceptance evidence, a hard
bound, and an explicit successor. Inner work follows:

```text
RE-PLAN -> BUILD -> PIN -> PROVE -> MEASURE -> SOL REVIEW -> COMMIT/PUSH -> EXIT
```

P02 through P32 each receive one implementation pass. Finish all implementation before running
the consolidated focused/full tests, benchmarks, install and bundle matrix, or independent review.
Do not start packet-level test/review loops. P32 owns the single integrated repair/release audit.
The owner has standing authorization for work after P32; do not ask for per-pass authorization.

## Chain

### L0 — plan review, baseline, and execution freeze

- **goal:** Sol approves an internally consistent, testable master plan and the repository
  records a reproducible baseline before feature implementation.
- **prompt:** Run the Sol plan-review packet, resolve all blocking/required findings, freeze
  the plan commit/hash, inventory current tests/install surfaces/runtime metrics, and create
  the issue-backed packet graph.
- **accept:** Sol plan verdict; frozen plan identifiers; baseline evidence; every plan
  requirement mapped to exactly one owner packet or an explicit exclusion; measurement,
  Control, interface, privacy, support, provenance, and schema contracts frozen; 93-test
  baseline green.
- **bound:** owner-authorized review/remediation until approval; no feature execution before approval.
- **exit →** L1.

### L1 — release integrity and canonical contracts

- **goal:** milestone 0 exits with synchronized metadata, reproducible distribution checks,
  truthful claims, and an executable control path.
- **prompt:** Execute milestone 0 as bounded packets for metadata/release validation,
  control parity, claim qualification, CI, and install-surface smoke tests.
- **accept:** every milestone 0 exit criterion maps to tests/evidence and Sol-approved commits.
- **bound:** per packet.
- **exit →** L2.

### L2 — acquisition and caption coverage

- **goal:** ordinary acquisition stays unchanged while classified, bounded recovery improves
  eligible YouTube failures and caption coverage.
- **prompt:** Execute milestone 1 as separate packets for the acquisition result contract,
  retry taxonomy/ladder, cookies/redaction, caption language/fallback, and Fathom's
  deferment.
- **accept:** frozen failure corpus improves; ordinary-path latency/completion does not regress;
  no secret disclosure; every fallback is reproducible.
- **bound:** per packet.
- **exit →** L3.

### L3 — pluggable local-first transcription

- **goal:** native captions, sidecars, local HTTP, YAP, Groq, and OpenAI share one normalized,
  privacy-aware interface with deterministic fallback.
- **prompt:** Execute milestone 2 as contract, sidecar, local HTTP, YAP, cloud-adapter, and
  diagnostics packets.
- **accept:** adapter accuracy/timestamps/latency/privacy/failure tests pass; no mandatory
  dependency or key; earlier successful adapters prevent later audio transmission.
- **bound:** per packet.
- **exit →** L4.

### L4 — range audio, safe resume, and portable evidence

- **goal:** focused work processes only needed audio and evidence state is resumable,
  bounded, private, verifiable, and portable.
- **prompt:** Own all Milestone 4 requirements here. Execute milestones 3–4 as packets for
  range extraction/timestamp restoration, silence-aware chunks, receipts/retries, cache
  correctness, bundle schema/replay/purge, question transport, progressive sufficiency,
  verified Scout reuse, frame/table mining, and conflicting-claim reconciliation.
- **accept:** range, corruption, concurrency, permission, replay, and retention gates pass.
- **bound:** per packet.
- **exit →** L5.

### L5 — question-aware and semantic evidence compilation

- **goal:** targeted questions receive less reader context without losing exactness, coverage,
  temporal obligations, privacy, or deterministic fallback.
- **prompt:** Consume completed Milestone 4 interfaces without re-owning them. Execute
  Milestone 5 as packets for lexical retrieval, coverage/temporal obligations, semantic
  fixtures and trigger, local/remote Adapters, OCR evaluation, and rank fusion.
- **accept:** exact-number/entity/negation/before-after fixtures do not regress; semantic work
  runs only where measured leverage exists; lexical-only remains supported.
- **bound:** per packet.
- **exit →** L6.

### L6 — dependency-free vision selection

- **goal:** improve or retain key-event recall and redundancy using only FFmpeg and
  standard-library Python.
- **prompt:** Execute milestone 6 as fixture/harness, scorer, temporal-diversity, and
  integration packets. Do not add OpenCV or PySceneDetect.
- **accept:** required-change fixtures have zero known false drops; any promoted policy is on
  the total-system Pareto frontier; losing signals are deleted.
- **bound:** per packet.
- **exit →** L7.

### L7 — confirmatory evaluation and v1.0 distribution

- **goal:** one frozen candidate receives an honest confirmatory verdict and, only if all
  gates pass, a reproducible v1.0 release.
- **prompt:** Validate the grader and freeze the analysis plan/candidate before P29 verifies
  the preregistered seal and authorizes its one opening; then run the untouched confirmatory
  set once, complete install/update/uninstall checks, obtain final Sol audit,
  and publish only supported claims and artifacts.
- **accept:** all final release gates pass; raw evidence and limitations publish; tag/artifact
  verify; final Sol audit clean; owner authorizes any public visibility change.
- **bound:** two instrument repairs; one confirmatory run; human visibility gate unbounded.
- **exit →** v1.0 complete or an evidence-backed successor chain.

## Invariants

1. No loop advances without `EXIT.md` verified against repository state.
2. Every metric-changing packet measures against the frozen upstream control and relevant
   cheapest-control mode.
3. Instrument failures and evidence failures are reported separately.
4. Terra never verifies its own work; Sol never implements while reviewing.
5. No OpenCV/PySceneDetect code or installer path may enter v1.0.
6. No private source, cookie, key, or audio is transmitted to an unenabled adapter.
7. The chain is append-forward; material replanning creates a successor document.
