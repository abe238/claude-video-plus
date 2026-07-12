# P05 provisional exit map

## Acceptance evidence

| Criterion | Evidence | Status |
| --- | --- | --- |
| Deterministic runtime-only ZIP | `tools/build_skill_bundle.py`; `tests/test_bundle.py` | focused tests passed |
| One SKILL.md, no dev files/bytecode | `tests/test_bundle.py` | 9 intended runtime files |
| Strictly below 250 KB | `tests/test_bundle.py` | 43,462 bytes in local receipt |
| Exact-tree review | `SOL-REVIEW.md` | single review complete; findings assigned to P32 |

P05 is implemented but makes no published-artifact or install-success claim. P06 owns install
proof; P32 owns the allowlist, size-refusal mutation, exact-tree evidence, and release artifact.
