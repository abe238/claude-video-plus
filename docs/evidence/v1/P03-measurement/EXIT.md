# P03 provisional exit map

This is provisional implementation evidence. It makes no Sol approval, performance, release, or
confirmatory-cohort claim.

## Acceptance evidence

| Acceptance criterion | Evidence | Current status |
| --- | --- | --- |
| MEAS-001 deterministic, checksum-linked raw gate derivation | `tools/evaluate_v1.py`; `tools/validate_v1_evidence.py`; evaluator/schema adversarial tests | locally exercised; pending Sol review |
| Exact paired rows, retained attempts/failures, asymmetric retry resource coverage, finite values, denominators, classes, and environments | `tests/test_v1_evidence_schema.py` | owner-directed final pass; final review pending |
| MEAS-002 frozen repeats, nearest-rank p95, cold/warm declared buckets, benchmark pair IDs separate from run attempts, and no-op sentinel coverage | `raw/jitter-fixture.json`; `jitter-evaluator-output.json`; `tests/test_v1_evaluator.py`; schema adversarial tests | synthetic formula fixture only; final review pending |
| Development-only continuation math, final token-target separation, deterministic case-hash arm order, retrieval temporal IoU/before-after, and all-column total-system/resource strict-regression derivation | `tools/evaluate_v1.py`; evaluator/schema adversarial tests | owner-directed final pass; final review pending |
| MEAS-003 family seal, exact opaque-identifier allowlist, no aliases/leakage, epoch freeze, custodian-only reserve access, and spent-cohort guard | `CORPUS-REGISTRY-v1.json`; `corpus-registry-validation.json`; `tests/test_corpus_registry.py` | synthetic placeholder registry; unopened/unspent; final re-review pending |
| Exact-tree independent review | `SOL-REVIEW.md` | owner-directed final review pending |

## Running v1 delta

| Metric | Control | Candidate | Delta |
| --- | ---: | ---: | ---: |
| Product performance | not measured | not measured | not applicable |
| Confirmatory cohort access | unopened | unopened | 0 exposures |
| Release claim | not evaluated | not evaluated | not applicable |
