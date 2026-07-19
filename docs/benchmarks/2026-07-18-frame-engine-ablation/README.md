# Frame-engine v2 ablation (2026-07-18)

Descriptive, n=3 corpus (43-min talk QacqRZ0vsD4, 22-min screencast ZW6d_2rwcdk,
2.5-min fast-cut zQnBQ4tB3ZA), v2-vs-v1 on THIS repo. This is the evidence
behind the 1.1.0 default flip. It is NOT a judged answer-quality comparison and
NOT a comparison against upstream 83da59f — that preregistered bake-off
(../2026-07-bakeoff/PROTOCOL.md) has not yet run.

run1 (post-dedup gap-fill only): max uncovered gap UNCHANGED (480.4s / 165.7s /
63.0s) — falsified the design half; led to the select-stage floor.
run2: inert build (metadata-key miswire), excluded as instrument failure,
regression-pinned in tests.
run3 (final, select-stage + gap-fill): max gap 87.0s / 45.1s / 30.0s — each
exactly the computed floor interval; A-B-A dupes collapsed (2/7/1); frame cost
within the 30% cap share (+17/+10/+1); wall time flat.

Columns: kept, dropped, max_gap_s, mean_gap_s, wall_s per arm
(v1 / v2-window-only / v2-full).
