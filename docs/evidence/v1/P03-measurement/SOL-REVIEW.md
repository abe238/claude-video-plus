# P03 Sol review

## Round 1 — exact staged-tree review

- Reviewer: Sol
- Reviewed tree: `cd1ea5a93e2145bd56abd12e1ea2f713b33acfa6`
- Exact verdict: **CHANGES_REQUIRED**

Required findings:

1. Canonical attempt accounting: usage/resources/failures need validated attempt identities;
   every failed attempt needs a distinct retained failure; denominators must include all
   attempts, failures, usage, and resource work.
2. Duration buckets must come from declared cases. Require every declared
   environment/state/duration bucket and unique repeat/pair identities so duplicate rows cannot
   manufacture 30 paired repeats.
3. Derive temporal IoU and before/after results from retrieval raw data; derive total-system
   cost/resource regression dimensions and canonical `strict_regressions` so Pareto is honest.
4. Reject locator/private content in corpus-registry values and require lowercase SHA-40
   candidate commits.

## Remediation status

Terra has implemented bounded P03-only remediations and adversarial tests for all four findings.
Re-review of the next exact staged tree is pending. No approval or closure is asserted.

## Round 2 — exact staged-tree review

- Reviewer: Sol
- Reviewed tree: `1253cda9f9708bce54ad8f9e58c2673eaf7f6fa8`
- Exact verdict: **CHANGES_REQUIRED**

Required findings:

1. Require resource work for every run attempt, including failed retries, with explicit no-op
   treatment.
2. Strict Pareto regressions must cover every total-system usage column and every reported
   resource dimension; no column may be silently ignored.
3. Development needs frozen paired-arithmetic-mean gates and its completion tolerance; only
   confirmatory uses family-clustered bootstrap and completion at Control.
4. Replace corpus locator heuristics with exact keys and opaque-identifier allowlists.
5. Correct provisional verification evidence and append the review history.

## Round 2 remediation status

Terra chose stricter integrity refusals where the frozen contracts do not define a softer rule:
every workload attempt must have resource evidence, every paired attempt has a no-op baseline,
token/cost dimensions use the frozen 2% band, calls and non-latency resources permit no increase,
and wall time uses the frozen jitter allowance. Re-review is pending; no approval is asserted.

## Owner-directed final implementation pass

The owner directed one implementation pass and one review for P02–P32, with the consolidated
full-suite audit deferred to P32. This is not a new diagnostic cycle. Terra treated every prior
Sol finding as an implementation input and added asymmetric-retry accounting, benchmark-repeat
pairing independent of arm attempts, development-only continuation math, and P01's frozen
SHA-256 case-ID arm-order rule. Final exact-tree review is pending; no approval is asserted.

Implementation inputs for this pass:

1. Candidate-only and Control-only retries retain their own attempt-linked work without a
   fictitious partner; benchmark no-op/pair evidence is independent of retry attempt numbers.
2. Development continuation reports token reductions and needs a declared-primary improvement
   outside noise, while the 50% targeted and 25% coverage targets remain confirmatory/final gates.
3. Paired runs use P01's SHA-256 case-ID parity order with unique `1/2`; asymmetric retries are
   representable without an invented opposite arm.

## Owner-directed single review result

- Reviewer model: `gpt-5.6-sol`
- Session: `019f576b-7804-7a22-ab67-345e8903dcef`
- Reviewed tree: `5bdf5cfc47bd37d2596f51d1be4c9c9888ad3d87`
- Verdict: **CHANGES_REQUIRED**

Release-blocking findings are assigned forward without another P03 pass:

1. Force development evidence to remain evaluation-only; P30 owns the frozen Candidate decision
   and P32 owns the final promotion audit.
2. Aggregate asymmetric-retry resources at total-system level and add missing call/transmitted
   dimensions in P30/P31 before a confirmatory verdict.
3. Bind confirmatory families and verdict evidence to the sealed registry/access journal in
   P29/P31 before the reserve cohort can be used.

P03 is **implemented, not release-complete**. These findings may not cross P32's release gate,
but the owner-directed single-pass policy permits downstream implementation to continue.
