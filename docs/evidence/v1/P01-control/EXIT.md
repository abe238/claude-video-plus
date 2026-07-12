# P01 provisional exit map

This packet is not closed. The entries below map acceptance criteria to implementation
evidence for the required independent review.

## Acceptance evidence

| Acceptance criterion | Evidence | Current status |
| --- | --- | --- |
| Exact clean detached upstream Control | focused fixture test and `live-local-control-snapshots/run.json` | verified locally |
| Dirty Control and unpinned tool refusal | focused refusal tests | verified locally |
| Fixed command, provenance, isolated upstream policy, and paired ordering | harness case validation and receipt assertions | verified locally |
| Caption expected/consumed identity and no-caption expectation | chronological yt-dlp snapshots plus focused URL/local drift tests | verified locally |
| Raw output preservation outside Control | local fixture run test and `live-local-control-snapshots/run.json` | verified locally |
| Independent review and immutable closure | `SOL-REVIEW.md`, reviewed tree, final receipt | pending |

## Running v1 delta

| Metric | Control | Candidate | Delta |
| --- | ---: | ---: | ---: |
| Benchmark outcomes | not measured | not measured | not applicable in P01 |

P01 adds the measurement guardrail only. It makes no performance or product-quality claim.
