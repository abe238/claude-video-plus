# P02 Sol review history

## Round 1 — exact-tree review

- Reviewer: Sol
- Session: `019f556d-7d3d-7ca0-a14a-1664ffaf5cbd`
- Reviewed tree: `5ad81f13e6ff9831e9111aee4e80120fe1b5d2b4`
- Exact verdict: **CHANGES_REQUIRED**

Verbatim findings:

1. Provider/network and process-call conformance is hardcoded, not observed. Instrument/observe calls for both arms and fallback; an extra Candidate provider/network call must trigger refusal. Do not assign constants.
2. Failure, timeout, and fallback-order conformance is neither implemented nor tested. Add paired deterministic fixtures covering success, categorized failure, timeout termination, and fallback attempt/order, and compare them.
3. normalize_text hides every absolute path outside declared temp roots; manifest_only_provenance suppresses arbitrary byte changes. Normalize only declared volatile roots and make any provenance allowance field/path-specific with a required fixture/disposition, or remove it.
4. Bind paired result to reviewed Candidate: repo/candidate relationship, clean/index/tree or staged-tree identity, Control commit, Candidate commit/config/tree, commands, environment, retry policy, routing version. Reject mismatch.
5. Measure comparable process invocation intervals for both arms and preserve the no-op samples/formula inputs so allowance is reproducible. Do not compare whole P01 harness setup with only Candidate child execution.
6. Complete route flag validation/mirroring: timestamps through the supported input boundary activates priority 2; reject whisper/no_whisper conflict and negative/blank/wrong-type values for all flags; add complete matrix/conflict/precedence tests.
7. Portable evidence must include sanitized raw stdout/stderr, commands with portable placeholders, no-op samples, detailed arm receipts, conformance record, failure/timeout/fallback cases, hashes, and no secrets/absolute paths/media/symlinks. EXIT must not overstate.

## Round 2 — exact-tree review

- Reviewer: Sol
- Session: `019f556d-7d3d-7ca0-a14a-1664ffaf5cbd`
- Reviewed tree: `155fce33293a7236078d33ab535cccdac6039b6b`
- Exact verdict: **CHANGES_REQUIRED**

Verbatim findings:

1. Real failure, timeout, and fallback conformance: synthetic Python snippets for both arms do not count. Build deterministic local fixtures or mocks that cause the actual frozen Control and Candidate watch commands to experience categorized failure, timeout termination, and fallback order. Integrate compare_outcomes into real run_pair results and derive fallback order from actual observed runtime output and calls, never constants.

2. Complete process and network observation: wrappers for four binaries are insufficient. Instrument direct Python socket and urllib HTTP plus arbitrary subprocess or executable paths within each arm, including absolute executables and wrapper-spawned real processes, so injected curl, direct socket, urlopen, or extra child causes refusal. Prefer a pinned per-arm Python audit or sitecustomize mechanism plus OS-supported child observation, with tests proving each evasion is caught. If comprehensive observation is impossible, narrow the contract truthfully and demonstrate structural offline blocking; do not claim what is not observed.

3. Fix per-arm raw hashes: never close over the last receipt variable. Store each receipt path and hash its own raw files; adversarial test must prove distinct raw bytes yield distinct correct hashes.

4. Routing: accept all runtime-supported fractional SS, MM:SS, and HH:MM:SS values and reject invalid or negative values. Expand visual priority semantics so ordinary graph-change, car-movement, and object-motion phrasing wins before speech keywords; add adversarial fixtures.

5. Boundary types and metadata: mirrored_flags must be a Mapping, not a list. Source kind must be an allowed pre-outcome kind and identity_sha256 a lowercase 64-hex digest. Refuse outcome-shaped or invalid values; tests.

6. Candidate binding: reject any tracked, staged, modified, or untracked content under complete skills/watch. Include every tracked and relevant untracked runtime file in identity or require a clean runtime subtree. Test dirty, staged, untracked, and runtime mismatch. An untracked import-shadowing module must be refused.

7. Evidence: generate the staged receipt directly from machine output and schema, not manual booleans. Stage sanitized observed process or audit logs and complete real success, failure, timeout, and fallback receipts sufficient to independently recompute every claim. Preserve raw hashes and artifact checksums; no media, secrets, private paths, or symlinks.

8. Preserve the complete verbatim review history, not a paraphrase.

## Owner-directed single-pass review

- Reviewer: Sol
- Session: `019f5775-2b85-78f2-99f5-856fc36cf4ad`
- Reviewed tree: `662dcebc7a3b37886a4025b7133567fe772cd6e1`
- Exact verdict: **CHANGES_REQUIRED**

Verbatim findings:

1. Executable/argv conformance is not enforced. Audit events record resolved executables and argv, but comparison checks only process and provider counts. Equal-count calls with different executables or arguments can conform. Audit subprocess values are also stringified, preventing reliable structural comparison.
2. Network isolation is overstated. `sitecustomize` blocks selected Python socket/urllib paths, including `sendto`, but permitted native children such as FFmpeg, ffprobe, and yt-dlp remain outside that interception. The fallback path additionally discovers tools through unpinned `shutil.which`; it does not use the same fully pinned P01 sandbox. Thus native network activity is neither structurally blocked nor completely observed.
3. Receipts are not independently derivable. The staged evidence contains summarized counts, booleans, argv, and raw hashes, but omits generated `process-events.jsonl`, per-arm `run.json`, `conformance.json`, and raw streams for the owner and round-3 runs. Consequently the process/network counts, resolved executable identity, argv equality, outcome classifications, and most raw hashes cannot be recomputed. This leaves the prior round-2 evidence finding unresolved.
4. Visual routing remains incomplete. Generic object-motion language is not recognized before speech terms. For example, “How does the ball move while they explain?” and “Where does the red box move while they explain?” route to rule 5/transcript instead of rule 3/balanced.

Verification notes:

- Sol independently reconstructed the exact reviewed tree.
- The P02 evidence validator passed.
- Sol's focused pytest rerun was infrastructure-blocked before collection because its read-only environment had no writable temporary directory. The implementation pass had already recorded 63 focused tests passing.
- Complete round-1 and round-2 review history remains above.

## Single-pass disposition

P02 is **implemented**, not release-complete. Per the owner-directed one-pass rule, it receives no
additional implementation or review loop. Findings 1–3 are assigned to P29–P32 for confirmatory
integrity and final release audit. Finding 4 is assigned to P23–P24, where temporal coverage and
semantic trigger behavior are implemented. P32 must close or explicitly refuse every finding
before release.
