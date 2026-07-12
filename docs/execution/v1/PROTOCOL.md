# v1.0 execution protocol

This protocol converts the approved strategic master plan into work that a smaller coding
model can execute reliably. It combines bounded Cascade loops with Parable's independent
author/reviewer separation.

## Roles

- **Coordinator:** owns decomposition, requirement traceability, deterministic verification,
  commits, pushes, and escalation.
- **Terra (`gpt-5.6-terra`):** implements one frozen, self-contained work packet at a time.
- **Sol (`gpt-5.6-sol`):** reviews the plan before execution and reviews Terra-authored work
  after deterministic checks. Sol remains read-only while reviewing.
- **Human owner:** decides explicit human gates and any scope expansion.

Terra never approves its own work. Sol does not silently repair work it is reviewing.
Review classifications map as `BLOCKING = P0`, `REQUIRED = P1`, and `OPTIONAL = P2`.
No unresolved P0 or P1 finding may cross a commit or push gate.

## Packet contract

Every packet names:

1. the frozen master-plan commit and requirement IDs;
2. one observable outcome;
3. owned and off-limits paths;
4. exact required behavior and failure behavior;
5. tests and live proof to add;
6. deterministic commands;
7. evidence output paths;
8. one implementation pass for packets P02 through P32. Under the owner's implementation-first
   direction, finish all remaining runtime/tooling slices before starting the consolidated test,
   benchmark, install, bundle, and independent-review phase. Do not pause for packet-level test or
   review loops; record ownership and repair failures once during the final audit;
9. stop conditions requiring escalation rather than invention.

The executor receives the packet and only the references named by it. It does not receive
the entire conversation or authority to reinterpret the master plan.

## Packet lifecycle

```text
PLANNED -> READY_FOR_TERRA -> IMPLEMENTING -> VERIFYING -> SOL_REVIEW
        -> CHANGES_REQUIRED -> IMPLEMENTING
        -> VERIFIED -> COMMITTED -> PUSHED -> COMPLETE

Any state -> AT_BOUND after its single authorized implementation/review pass. P32 owns the one
consolidated release repair/audit pass for cross-packet or release-blocking findings.

After its pass, a packet with unresolved findings is `implemented`, not `complete`. Its findings
must name a downstream owner and may not cross P32's release gate. Downstream packets may build on
an `implemented` dependency; only P32 may promote the chain to release-complete after consolidated
repair, the full suite, and final audit.
```

The coordinator integrates implementation slices first. After the complete Candidate exists,
verification runs from cheap deterministic checks through the full suite, install/bundle matrix,
benchmarks, and one independent final review. Failures are repaired in that consolidated phase so
the owner can evaluate or publish an earlier coherent Candidate without waiting on 31 test loops.

## Verification order

1. all planned implementation paths are present and integration is complete;
2. changed paths match requirement ownership;
3. focused tests, then the full test suite;
4. Python compilation and manifest/schema validation where applicable;
5. live-path proof and benchmark slice where the packet changes runtime behavior;
6. evidence files contain non-null results and environment/provenance;
7. stage the exact packet-owned tree and record its Git tree hash;
8. Sol compares that staged tree and provisional evidence against every acceptance criterion;
9. the coordinator commits and pushes only after Sol returns no unresolved P0/P1 finding;
10. commit the exact Sol-approved semantic tree;
11. a deterministic finalizer may change only registry approval/hash/commit fields,
    P00/GOV closure state, append one canonical approval envelope to the byte-preserved L0
    Sol-review history, preserve the reviewed L0 EXIT mapping, and finalize only declared
    fields in the reviewed verify receipt. It verifies the plan commit's
    tree equals Sol's approved tree, freezes a composite hash of every normative file, and
    rejects every other path, replacement/truncation of review history, or semantic registry change;
12. commit and push that mechanical finalization. Any non-whitelisted change returns to Sol.

## Evidence and traceability

Each packet writes under `docs/evidence/v1/<packet-id>-<slug>/`:

- `verify.json` — commands, exit codes, environment, and commit identifiers;
- metric or live-trace artifacts required by the packet;
- `SOL-REVIEW.md` — complete findings and their disposition;
- `EXIT.md` — acceptance criterion to evidence mapping and running v1 delta table.

`docs/execution/v1/REQUIREMENTS.json` maps every master-plan requirement to packets,
GitHub issues, tests, evidence, Sol verdicts, and commits. A requirement cannot be marked
complete from a commit message alone. The registry validator rejects unknown IDs, missing
owners/gates/failure behavior, duplicate packet ownership, and plan-hash drift.

## Git and GitHub policy

- Use GitHub Issues as the task graph.
- Owner-directed work does not require a pull request.
- Execute one overlapping packet at a time; independent packets require disjoint paths.
- Terra does not push. The coordinator stages only packet-owned files, commits after Sol
  approval, pushes `main`, and verifies remote HEAD.
- Future outside contributors use branches and pull requests.

## Public-claim gate

No packet may turn a development result into a general superiority claim. Only the final
confirmatory loop may authorize a claim, and only when its preregistered gates pass.
