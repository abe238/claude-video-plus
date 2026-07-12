# P05 Sol review

- Reviewer: Sol
- Reviewed tree: `1d493ee17f8a5fa715e17a837c14675d5ad4d5a1`
- Verdict: **CHANGES_REQUIRED**

Findings:

1. `runtime_files()` discovers every future `scripts/*.py`; the test derives its expected list
   from the same glob, so an unintended Python helper could enter the bundle unnoticed.
2. The size test proves only that today's output is below 250 KB; it does not exercise refusal and
   output deletion with an oversized high-entropy fixture.
3. `verify.json` was not bound to the exact reviewed tree, and its whitespace receipt did not
   explicitly name the staged/tree-scoped check.

## Single-pass disposition

P05 is **implemented**, not release-complete. Per the owner-directed one-pass rule it receives no
second implementation or review. P32 must replace discovery with an explicit runtime allowlist,
exercise oversized-output refusal/deletion, bind final evidence to its exact tree, and verify the
clean release artifact before publication.
