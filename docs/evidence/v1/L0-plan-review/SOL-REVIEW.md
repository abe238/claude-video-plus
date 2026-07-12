# Sol plan review — initial pass

Model: `gpt-5.6-sol`, reasoning effort `xhigh`, read-only sandbox

Session: `019f5400-0810-7710-9053-06aeeee6cc3d`

Verdict: **CHANGES_REQUIRED**

## Complete findings and disposition

| ID | Class | Finding | Disposition |
| --- | --- | --- | --- |
| SOL-001 | BLOCKING | Approval/canonical revision was contradictory and unfrozen. | Owner approval recorded; plan status corrected; plan/hash freeze and ready validation added. |
| SOL-002 | BLOCKING | No atomic stable requirement IDs or complete traceability registry. | `REQUIREMENTS.json` now owns stable requirements and packet DAG; validator added. |
| SOL-003 | BLOCKING | Frozen Control, Candidate fallback, and cheapest Control were conflated. | Separated and frozen in `CONTROL.md`; master wording corrected. |
| SOL-004 | BLOCKING | Quality, recall, latency, ASR, Pareto, and failure gates were not decision-complete. | Formulas, margins, repetitions, missing-data rules, and promotion rules frozen in `MEASUREMENT.md`. |
| SOL-005 | REQUIRED | Development/confirmatory separation was not operationally sealed. | Family definition, corpus registry, custodian, access log, freeze, and spent-cohort rules specified. |
| SOL-006 | REQUIRED | Milestone 4 ownership overlapped L4/L5; incomplete features could become default. | L4 owns Milestone 4; L5 consumes it; `CONTRACTS.md` keeps incomplete work disabled/non-default. |
| SOL-007 | REQUIRED | Result/failure/retry/fail-open semantics were undefined. | Normalized states, exits, acquisition/transcription/cache exhaustion rules specified in `CONTRACTS.md`. |
| SOL-008 | REQUIRED | “CLI exposes” contradicted the slash-command product contract. | Master corrected; cross-host invocation/config/internal-runtime contract specified. |
| SOL-009 | REQUIRED | Retention/privacy defaults omitted transcripts, OCR, embeddings, URLs, identities, and logs. | Data-class retention/transmission matrix and secret-scan gate specified. |
| SOL-010 | REQUIRED | Supported environment/install/update/rollback matrix was unfrozen. | Tiered environment matrix and isolated procedures specified in `SUPPORT.md`. |
| SOL-011 | REQUIRED | Fork mechanisms lacked definitive disposition and license/credit tracking. | `PROVENANCE.md` records ship/evaluate/defer/exclude and credit obligations. |
| SOL-012 | BLOCKING | Review severity and post-review commit finalization allowed fake closure. | P0/P1 mapping, exact staged-tree review, deterministic finalizer, and semantic-change re-review added. |
| SOL-013 | REQUIRED | Metric evidence had no canonical schemas or validation rules. | Canonical raw/derived filenames, required fields, and rejection rules specified in `EVIDENCE-SCHEMAS.md`. |

Feature execution remains stopped until Sol reviews these dispositions and returns `APPROVE`.

## Second pass

Reviewed staged tree: `fa8978eb06bf035f912e720e24ab65a2da26f059`

Session: `019f540d-8020-7743-bb56-c3e8de68009c`

Verdict: **CHANGES_REQUIRED**

| ID | Class | Finding | Disposition |
| --- | --- | --- | --- |
| R1 | BLOCKING | Finalization remained self-contradictory, accepted fabricated object IDs, and hashed only the master plan. | Exact Git object validation, approved-tree equality, a composite normative manifest, a mechanical finalizer allowlist, and semantic-registry comparison were added. |
| R2 | BLOCKING | The registry lacked source anchors, issues, tests, evidence, verdicts, commits, and several Milestone 4 requirements. | Atomic catalog anchors, full packet trace fields, GitHub issue mapping, and the missing sufficiency, reader, conflict, and Scout requirements were added. |
| R3 | BLOCKING | Measurement computations were underspecified. | The answer rubric, evidence matching, missing-output scores, bootstrap, percentile, noise, latency, and ASR comparator rules are now executable and covered by a golden evaluator. |
| R4 | REQUIRED | The confirmatory seal was scheduled after metric-changing development. | Source-family assignment and sealing moved to P03; P29 only verifies that pre-development seal and authorizes its one opening. |
| R5 | REQUIRED | L4 and L5 still overlapped. | L4 now owns range/state/question/progressive-reader behavior; L5 owns retrieval, coverage, semantic adapters, OCR evaluation, and fusion. |
| R6 | REQUIRED | Fathom was simultaneously evaluation-only and deferred. | Fathom is consistently deferred outside v1. |
| R7 | REQUIRED | Evidence prose was not machine-enforceable and a null-plan-hash baseline claimed completion. | A versioned machine schema, validator, positive/negative fixtures, and provisional baseline state were added. |

Feature execution remains stopped until a subsequent Sol review returns `APPROVE` for an exact staged tree.

## Third pass

Reviewed staged tree: `57856188133fcb1008d03906a60dd9da7543637d`

Session: `019f5423-32b5-7983-9caf-0b0c5eb6fe95`

Verdict: **CHANGES_REQUIRED**

- **P0 / R7:** per-record evidence shapes did not enforce promised cross-artifact closure rules.
- **P0 / R3:** evaluator and evidence schema disagreed, and several frozen gates were not executable.
- **P0 / R2:** completed packets could use fake issues, tests, commits, verdicts, and closure evidence.
- **P1 / R1:** finalization normalized the entire Sol review object and could replace semantic metadata.
- **P1 / R4:** the DAG allowed confirmatory opening before grader validation and Candidate freeze.

Feature execution remains stopped until a subsequent Sol review returns `APPROVE` for an exact staged tree.

## Fourth pass

Reviewed staged tree: `862535bb26b5291acb4e67b2d4bb3c61872d8430`

Session: `019f5430-aa10-7532-adaa-18cc39805acc`

Verdict: **CHANGES_REQUIRED**

- **P0 / R7:** raw evidence types were not linked strongly enough to prevent self-asserted gate closure.
- **P0 / R3:** aggregate inputs could be underpowered and evaluator output was not a schema-valid gate artifact.
- **P0 / R2:** issue, check, checksum, review, and commit receipts were still forgeable.
- **P1 / R1:** finalization could replace, rather than append to, the review history.
- **P1 / R4:** P31 did not depend on P29's authorized opening.

Feature execution remains stopped until a subsequent Sol review returns `APPROVE` for an exact staged tree.

## Fifth pass

Reviewed staged tree: `d2554c45909c63ac2f957896625592b357107127`

Session: `019f5441-60b4-7db0-b3b4-52b18a01c69c`

Verdict: **CHANGES_REQUIRED**

- **P0:** ASR rows could reference a case absent from canonical cases.
- **P0:** closure commands and EXIT evidence were not bound to the reviewed tree/session.
- **P1:** approval append logic stripped trailing bytes and accepted a non-UUID session token.

Feature execution remains stopped until a subsequent Sol review returns `APPROVE` for an exact staged tree.

## Sixth pass

Reviewed staged tree: `e37e6a2a63eed35c9900b3e49d9b1fcd54fbec6a`

Session: `019f5448-1065-72b0-be4a-739825ef2a26`

Verdict: **CHANGES_REQUIRED**

- **P1:** exact Git blob and EXIT comparisons stripped whitespace instead of preserving bytes.
- **P1:** session validation checked only the last text block rather than the complete final message.

The owner explicitly authorized one final remediation and Sol pass.

## Seventh pass

Reviewed staged tree: `48352c38146c3eeb0a3a159ecffe44591ccc6de2`

Session: `019f54af-4ef1-74f0-bd30-8e141f63c4f5`

Verdict: **CHANGES_REQUIRED**

- **P1:** text-mode Git output and file reads normalized line endings, so LF-to-CRLF rewrites
  could evade byte-exact review and EXIT comparisons.

The owner explicitly authorized one final byte-integrity remediation and eighth Sol pass.

## Eighth pass

Reviewed staged tree: `102e9328fe108d96c8bbc7ffac8dae5bb765fe11`

Session: `019f54ba-cd5d-74f0-a146-dd0a07ebca9f`

Verdict: **CHANGES_REQUIRED**

- **P1:** the byte-mode remediation was correct, but its regression test exercised only an
  in-memory helper. It did not prove that validator-level Git/file reads reject LF-normalized
  rewrites of committed CRLF `SOL-REVIEW.md` and `EXIT.md` artifacts.

The validator-level regression tests now use a real temporary Git repository and exercise both
artifact paths. The owner has given standing authorization to continue Sol review/remediation
until approval without repeated per-pass authorization requests.

## Final approval

Model: `gpt-5.6-sol`

Session: `019f54c5-f5b9-7591-9611-4eb6ad791ade`

Approved staged tree: `b280c7e82bb045101e44943135f75bb3f546aebd`

Final verdict: **APPROVE**
