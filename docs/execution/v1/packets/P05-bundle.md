# P05 — Lean deterministic watch.skill bundle

## Frozen inputs

- Requirement: `DIST-002`
- GitHub issue: `#7`
- Dependency: P04 implemented under the owner-directed one-pass policy.

## Observable outcome

The bundle builder emits a byte-reproducible ZIP rooted at `watch/`, with exactly one `SKILL.md`
and the Python runtime modules. It excludes build helpers, scanner configuration, bytecode, docs,
tests, media, and models, and refuses output at or above 250 KB.

## Focused verification

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_bundle.py
python3 -m compileall -q tools/build_skill_bundle.py tests/test_bundle.py
python3 tools/validate_v1_evidence.py docs/evidence/v1/P05-bundle/verify.json
git diff --check
```

P05 receives one implementation pass and one Sol review. The clean-tree release invocation and
published artifact are independently verified in P32; no full suite runs here.
