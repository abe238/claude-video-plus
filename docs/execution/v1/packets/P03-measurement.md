# P03 — Measurement evaluator, jitter fixtures, and corpus seal

## Frozen inputs

- Master-plan commit: `edc2ce6696a88501f19060cc2000ed4f513c6133`
- Requirements: `MEAS-001`, `MEAS-002`, `MEAS-003`
- GitHub issue: `#5`
- Frozen Control: `83da59fa78c3eee9e20f515fe75c438bb5166efd`
- Prerequisite packet: P00

## Observable outcome

Versioned evaluator and evidence validation derive measurement and release-gate receipts only
from checksum-linked canonical JSONL.  A machine-readable corpus registry assigns synthetic
source identities and complete families to development or sealed confirmatory cohorts before
metric-changing work, and tamper-evident access records enforce the confirmatory boundary.

## Ownership and limits

Owned paths are `tools/evaluate_v1.py`, `tools/validate_v1_evidence.py`,
`tools/corpus_registry.py`, `tests/test_v1_evaluator.py`, `tests/test_v1_evidence_schema.py`,
`tests/test_corpus_registry.py`, `docs/execution/v1/CORPUS-REGISTRY-v1.json`, this packet, and
`docs/evidence/v1/P03-measurement/**`. Runtime, registry metadata, public documentation,
normative measurement/schema/requirements files, and P00/P01/P02 paths are off limits.
P03 makes no performance or release claim.

## MEAS-001 — canonical raw evidence

- The evaluator version is emitted in every derived receipt and recomputes all denominators,
  coverage, aggregates, gates, and Pareto verdict from the linked raw JSONL only.
- Canonical inputs are exactly `cases`, `runs`, `judgments`, `retrieval`, `usage`, `resources`,
  and `failures`; release scope adds install, privacy, and provenance; applicable ASR adds ASR.
  A summary, duplicate canonical filename, unrelated row, missing canonical file, checksum
  mismatch, or raw input outside the receipt directory is an integrity refusal.
- Every case has exact Control/Candidate final runs. Usage, resource, and failure rows carry the
  matching positive attempt identity; each failed attempt has exactly one retained failure row.
  Attempts are contiguous from one and all attempt, failure, usage, and resource work remains in
  denominators/receipts. There are no null, NaN, infinity, or mixed-unit substitutions for a
  derived value. Positive denominators are required where a gate is derived.
- Required classes and environments must have paired case/run coverage. Derived fields are never
  trusted from a supplied receipt; adversarial mutation tests cover every derived field and raw
  linkage.

## MEAS-002 — frozen latency rules

- Bucket key is `(environment_id, cold|warm state, duration bucket)`; duration is obtained from
  declared case metadata, never the observed resource rows or an outcome. Every supported bucket
  has at least 30 no-op, 30 Control, and 30 Candidate finite millisecond samples. Resources carry
  unique repeat IDs and matched Control/Candidate pair IDs, preventing duplicate rows from
  manufacturing repeat counts.
- Percentiles are nearest-rank; p95 requires at least 20 finite values. Jitter is exactly
  `max(5 ms, 5% * Control median, no-op p95 - no-op p50)`. Candidate median and p95 each must
  be within it. Cold and warm remain separate.
- The fixture is machine-readable, checksum-linked, replayed by the evaluator, and rejects a
  single run, missing/mixed bucket, nonfinite values, wrong unit, or post-outcome allowance.
  Failure work remains in raw usage/resources/failure evidence.

## MEAS-003 — corpus seal

- Registry identities are SHA-256 placeholder labels only: no URL, path, media bytes, caption,
  or private metadata. A family is wholly development or confirmatory; identity aliases and
  reassignment are rejected.
- The registry freezes candidate/config/routing/prompt/reader/grader/evaluator epochs,
  supported classes/environments, exclusions, and powered minima before any confirmatory access.
  Development executors may list development identities only.
- Confirmatory access requires a custodian authorization; its append-only JSONL log is
  hash-chained. An authorized opening differs from an exposure: exposure spends the cohort.
  Reserve access without a log is refused; a spent cohort cannot be reused. Outcome-aware
  exclusions and underpowered claims are refused.

## Tests and deterministic proof

```text
python3 -m pytest -q tests/test_v1_evaluator.py tests/test_v1_evidence_schema.py tests/test_corpus_registry.py
python3 -m compileall -q skills tools tests
python3 tools/validate_v1_execution.py
python3 tools/validate_v1_evidence.py docs/evidence/v1/P03-measurement/verify.json
git diff --check
```

Evidence includes generated synthetic raw fixtures and evaluator output, corpus seal/access-log
validation receipts, checksums, tool/environment provenance, provisional `verify.json`, pending
`SOL-REVIEW.md`, and `EXIT.md` with the exact phrase `Acceptance evidence`.

## Bounds and stop conditions

At most two valid PROVE failures and three Sol review/fix rounds apply. Stop for a contradiction
that requires changing `MEASUREMENT.md`, `EVIDENCE-SCHEMAS.md`, `evidence-schema-v1.json`, or
`REQUIREMENTS.json`; for a request to access real confirmatory identities; or for any change to
P02's staged/untracked tree. Do not stage, commit, push, or self-approve.

## Strict ambiguity resolution

Where the frozen contracts require no-regression accounting but do not define a separate softer
threshold, P03 refuses the looser interpretation: all-model input/output, reader text/image, and
dollars use the frozen 2% token/cost band; calls and CPU/RSS/disk/network/process/
initialization dimensions permit no increase; wall time uses only the frozen jitter allowance.
Every workload run attempt needs resource evidence, while no-op baselines belong to their declared
benchmark buckets rather than individual arm attempts. These are integrity refusals, not new
product-performance claims.

## Owner-directed final implementation pass

The owner has directed one implementation pass and one review for P02–P32, with the consolidated
full-suite audit deferred to P32. This P03 pass consumes the prior Sol findings as implementation
inputs: canonical attempt/resource accounting, repeat-bucket pairing, all-column regressions,
split-specific gates, corpus allowlists, asymmetric retries, and deterministic arm order. It does
not open a new diagnostic cycle. Actual run attempts retain their own usage/resource/failure work;
benchmark no-op rows use attempt sentinel `0`, and repeat pairing is carried only by non-null
measurement `pair_id` values. For each paired attempt, SHA-256(case ID)'s first-byte parity maps
even to `Control=1, Candidate=2` and odd to `Candidate=1, Control=2`; an asymmetric retry has no
invented partner or pair-order comparison.
