# Benchmarks — supplemental evidence data

Raw data behind the claims in the top-level README. This folder is **not** part of the
install package (`.skillignore` excludes `docs/`; the claude.ai bundle archives only
`skills/watch/`).

## Methodology (applies to every entry)

- **Paired design**: the original pipeline (control, `balanced` mode at commit-equivalent
  behavior) and the evidence pipeline run against the *same* video and the *same*
  questions.
- **Symmetric answering**: one answering agent per pipeline, identical instructions,
  each sees only its own pipeline's evidence.
- **Blind judging**: 3 LLM judges per round grade both answer sets 1–10 on correctness
  vs the transcript, completeness, citation accuracy (spot-checked ≥3 citations per
  answer), and hype-exclusion where asked. Judges don't know which pipeline is which;
  at least one judge per panel sees the labels position-swapped.
- **Token accounting**: text tokens ≈ chars/3.6; image tokens = (w×h)/750 at the actual
  512×288 frame size (197/frame), per Anthropic's published formula.

## Honest limitations

LLM judges are a measured-but-imperfect instrument (panel-to-panel variance is visible
in the raw scores — the *paired per-round* comparison is the meaningful number). This is
measurement with auditable raw data, not a preregistered statistical trial; the full
statistical protocol (preregistered margins, family-clustered bootstrap, dev/confirmatory
corpus split) is specified in [../plans/V1.0-MASTER-PLAN.md](../plans/V1.0-MASTER-PLAN.md)
and [../execution/v1/MEASUREMENT.md](../execution/v1/MEASUREMENT.md)
and gates any stronger public claim. Where the evidence pipeline loses, the loss ships
here unedited.

## Entries

- [2026-07-11-opencv-ablation/](2026-07-11-opencv-ablation/) — negative development
  result: the OpenCV composite recovered fewer curated moments than the current 16×16
  scorer (5/12 vs 6/12), took about 4.8× as long to score, and did not reduce reader
  tokens. OpenCV was rejected for v1.0; the report includes limitations and raw JSON.
- [2026-07-11-single-video-deep-dive/](2026-07-11-single-video-deep-dive/) — 38-min
  launch video ("AI News: GPT-5.6…", Matt Wolfe), 3 question classes, 5 iteration
  rounds. Final: coverage **win** (9.33 vs 8.33) at −60% tokens, targeted-cost **tie**
  (9.00) at −77%, targeted-feature **win** (9.33 vs 8.33) at −79%. Includes the round-0
  result where a naive retrieval candidate *lost* 3–0 — kept because it shows what the
  shipped mechanisms (numeric guard, chapter roll-up, frame-mining, reconciliation)
  actually fix.
- [2026-07-12-multi-video-battery/](2026-07-12-multi-video-battery/) — 4 videos, 12 questions,
  measured at commit `b90ae21`: mean token reduction **80%**, overall quality parity (control
  8.64 vs evidence 8.58 mean). Duration split is the real finding — 0 wins/0 ties/3 losses on
  the one video under 8 min, vs 5 wins/2 ties/2 losses on videos 8 min and up. A 5th video
  (Veritasium) was collected but its judge panel hit a session limit; excluded from all
  aggregates, raw answers included unjudged.
