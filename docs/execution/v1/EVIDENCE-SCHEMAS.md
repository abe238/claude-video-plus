# Evidence artifact schemas

All artifacts use UTF-8 JSON or JSONL, include `schema_version: 1`, and retain raw rows. The
machine-readable types, nullability, enums, key patterns, and units live in
`evidence-schema-v1.json` and are enforced by `tools/validate_v1_evidence.py`. A derived report
without its referenced raw inputs is invalid.

## Common provenance

Every artifact contains:

```text
schema_version, artifact_type, created_at_utc, packet_id, requirement_ids,
control_commit, candidate_commit, candidate_config_hash, plan_sha256,
environment_id, tool_versions, command_or_protocol, status
```

`status` is one of `provisional`, `complete`, `failed`, `partial`, or `invalid`. Only
`provisional` planning/baseline evidence may omit frozen plan/commit identifiers; it cannot
satisfy a feature or release gate. Null/missing outcomes and failures remain explicit rows.

## Canonical files

| File | Required row fields |
| --- | --- |
| `cases.jsonl` | case_id, source_family_id, split, Question class, source metadata hash, explicit flags, obligations, gold Evidence spans or null with reason |
| `runs.jsonl` | case_id, arm, attempt, order, command/config, start/end, result state, failure class, raw manifest path |
| `judgments.jsonl` | case_id, post-blinding arm mapping, arm_blinded, judge/human epoch, criterion scores, citations checked, refusal/failure, position order |
| `retrieval.jsonl` | case_id, arm, Evidence span IDs, rank/scores by signal, gold match, temporal IoU, before/after result |
| `usage.jsonl` | case_id, arm, reader text/image usage, all-model input/output, calls, dollars, estimated/reported marker |
| `resources.jsonl` | case_id, arm, cold/warm, wall/CPU, peak RSS, disk, network, process calls, initialization |
| `failures.jsonl` | case_id, arm, stage/Adapter, normalized failure, retry eligibility, fallback, disclosed warning, final state |
| `asr.jsonl` | case_id, arm, language, frozen comparator/availability, raw S/D/I/reference-word counts, raw boundary errors |
| `install-results.jsonl` | environment_id, surface, operation, clean-state inventory, exit, duration, artifact checksum/size, cleanup state |
| `privacy-scan.jsonl` | fixture/secret class, artifact/path, expected disposition, observed match count, pass |
| `provenance.jsonl` | mechanism, disposition, origin user/repo/revision, inspiration/adaptation/code, license, public credit locations |
| `gate-results.json` | evaluator/split/scope, frozen powered-family minima, margins, derived denominators, all aggregates/CIs, every gate pass/fail, canonical raw paths/checksums |
| `verify.json` | commands/checks, exit codes, reviewed Git tree hash, environment, artifact checksums |

## Validation rules

The validator rejects:

- unknown schema/artifact/status/arm/failure values;
- missing denominators, commits, plan hash, environment, or packet/requirement IDs;
- null outcomes not paired with a failure/invalid reason;
- unmatched paired Control/Candidate cases;
- duplicate case/arm/attempt keys;
- a confirmatory case sharing a source family with development;
- summaries whose raw file paths/checksums are missing;
- token estimates presented as provider-reported usage;
- dropped failures or attempts;
- a passing gate whose required class/environment has no rows;
- evidence paths outside the packet-owned evidence directory.

Gate results are receipts, not trusted summaries. `tools/evaluate_v1.py` derives their
denominators, covered classes/environments, aggregates, gate booleans, and Pareto verdict from
the checksum-linked canonical JSONL files. `tools/validate_v1_evidence.py` loads and validates
those files, requires matching frozen packet/requirement/commit/config/plan provenance, reruns
the evaluator, and rejects any difference. Extra non-canonical inputs and rows whose case is not
in the linked `cases.jsonl` are invalid.

A measurement-scope gate requires `cases`, `runs`, `judgments`, `retrieval`, `usage`,
`resources`, and `failures`. A release-scope gate additionally requires install, privacy-scan,
and provenance rows. `asr.jsonl` is mandatory when `asr_applicable` is true; ASR may be marked
not applicable only when no ASR mechanism is under promotion. Provider usage and ASR gates are
derived from raw observations, never supplied as trusted aggregates.

Confirmatory metadata cannot self-declare a trivially powered cohort: the frozen powered count
must be met and may never be below five independent source families overall or three families
in every supported Question class. These are absolute integrity floors, not substitutes for the
pilot-powered larger sample size. A spent or underpowered cohort cannot produce a valid gate.

Environment IDs form a closed vocabulary in `evidence-schema-v1.json`. Packet and requirement
IDs are loaded from `REQUIREMENTS.json`; unknown IDs and requirements attributed to the wrong
packet are invalid. A complete case must have non-empty obligations and either well-formed gold
point/interval evidence or a non-empty reason that gold evidence is unavailable.

## Packet closure files

`SOL-REVIEW.md` contains the exact approved semantic tree hash, verdict, complete findings, and
dispositions. `EXIT.md` maps every acceptance criterion to a file/checksum and carries the
running delta table. The finalizer must preserve the review file from the approved tree byte for
byte and append exactly one canonical model/session/tree/verdict envelope. After the approved
semantic tree is committed, the finalizer may change only
the fields and paths whitelisted in `PROTOCOL.md`; the registry validator compares the finalizer
commit with the approved plan commit and invalidates every other mutation.
