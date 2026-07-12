# P04 — Canonical release integrity and provenance

## Frozen inputs

- Requirements: `DIST-001`, `ATTR-001`
- GitHub issue: `#6`
- Dependencies: P02 and P03 are implemented under the owner-directed one-pass policy.

## Observable outcome

Repository manifests, public claims, release history, CI, derivative identity, and gratitude all
agree. Every evaluated mechanism names its originating GitHub user and repository and states
whether it is inherited, independently adapted, deferred, excluded, or merely inspirational.

## Ownership and limits

P04 owns canonical release/provenance documentation, `tests/test_release_integrity.py`,
`tests/test_attribution.py`, this packet, and `docs/evidence/v1/P04-release-integrity/**`. It makes
no feature, benchmark, install-success, or published-release claim. P05–P06 own bundle and install
proof; P32 owns the consolidated suite, artifact, tag, and final audit.

## Focused verification

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_release_integrity.py tests/test_attribution.py
python3 tools/validate_v1_execution.py
python3 tools/validate_v1_evidence.py docs/evidence/v1/P04-release-integrity/verify.json
git diff --check
```

P04 receives one implementation pass and one Sol review. Unresolved findings are assigned to a
later owning packet and must be closed by P32; P04 is not rerun.
