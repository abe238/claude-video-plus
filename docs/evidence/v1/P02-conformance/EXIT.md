# P02 provisional exit map

This evidence is provisional. It makes no Sol approval claim and cannot close P02.

## Acceptance evidence

| Acceptance criterion | Evidence | Current status |
| --- | --- | --- |
| CTRL-003 priorities 1–6, complete flags, and versioned decision | `tests/test_control_conformance.py`; `tools/control_conformance.py` | implemented; generic object-motion finding assigned to P23–P24 |
| Outcome-derived/unknown routing input refused structurally | adversarial routing tests | locally exercised; pending re-review |
| CTRL-002 paired clean Control/Candidate behavior and Candidate binding | `round1-conformance.json` paired run | locally exercised; pending re-review |
| Sanitized raw stdout/stderr, frame/transcript/manifest, process/provider calls, commands, and raw hashes | `raw/`; `round1-conformance.json` | locally recorded; pending re-review |
| Comparable payload interval, no-op samples, and allowance formula | `round1-conformance.json` | locally recorded; pending re-review |
| Success/failure/timeout/fallback-order fixtures | `round1-conformance.json`; focused tests | locally exercised; pending re-review |
| Real frozen-Control/Candidate success, failure, timeout, and runtime fallback | `round3-real-fixtures.json` | locally recorded; pending re-review |
| Owner single-pass exact audit/success receipt | `owner-single-pass.json` | locally recorded; pending Sol review |
| Actual local evidence fail-open once to balanced | `round1-conformance.json` | locally exercised; pending re-review |
| Exact-tree independent review | `SOL-REVIEW.md` | single-pass review complete; changes required and assigned downstream |

## Running v1 delta

| Metric | Control | Candidate | Delta |
| --- | ---: | ---: |
| Local compatibility completion | 1/1 | 1/1 | 0 |
| Provider/network calls | 0 | 0 | 0 |
| Performance claim | not measured | not measured | not applicable |

P02 is implemented but remains provisional under the owner-directed single-pass policy. It
establishes no release, approval, or improvement claim. P29–P32 own its unresolved integrity and
receipt findings; P23–P24 own its generic object-motion routing finding.
