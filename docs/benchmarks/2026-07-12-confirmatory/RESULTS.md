# Sealed confirmatory evaluation — 2026-07-12

The one-shot confirmatory run authorized by the owner on 2026-07-12 and gated by
[receipt.json](receipt.json) (`status: authorized_once`; the receipt tool refuses re-runs).
Candidate: sealed commit `e0e5499` / config hash `122dac66…` — behaviorally identical to
released v1.0.0 (the only diff is two version-string lines). Corpus: five source families
never used in any development work, registered as opaque identities in the corpus registry
(custodian keeps the source mapping outside the repository) with a validated append-only
access log.

## Verdict

**Quality parity at roughly half the reader tokens.** Ten questions across five untouched
videos: evidence mode **3 wins / 4 ties / 3 losses**, mean blind-judge quality **8.83 vs
8.80** (control) — a dead heat well inside the grader's measured noise band — with mean
gold-fact coverage **3.67 vs 3.57** and a **56% mean evidence-token reduction**. Under the
project's Pareto rule (promote only if at least one primary outcome improves beyond jitter
and none is strictly worse), evidence mode passes as an opt-in: tokens improve decisively,
quality does not move.

| Video | Question | Control tok | Evidence tok | Δ | Quality (ctl vs ev) | Gold facts | Verdict |
|---|---|---|---|---|---|---|---|
| Kurzgesagt · memories (13:56) | coverage | 24,334 | 10,523 | −57% | 9.00 vs 9.00 | 4.0 vs 4.0 | tie |
| Kurzgesagt · memories | targeted | 24,334 | 5,401 | −78% | 9.00 vs 9.00 | 2.0 vs 2.0 | tie |
| MKBHD · OnePlus (15:04) | coverage | 24,699 | 11,298 | −54% | 9.00 vs 8.33 | 4.0 vs 4.0 | **loss** |
| MKBHD · OnePlus | targeted | 24,699 | 6,569 | −73% | 9.00 vs 8.33 | 4.0 vs 4.0 | **loss** |
| TED · inner voices (14:32) | coverage | 11,444 | 9,819 | −14% | 8.33 vs 9.00 | 4.0 vs 4.0 | win |
| TED · inner voices | targeted | 11,444 | 4,032 | −65% | 9.00 vs 9.00 | 4.0 vs 4.0 | tie |
| Veritasium · least action (32:44) | coverage | 29,783 | 16,387 | −45% | 8.67 vs 9.00 | 4.0 vs 4.0 | win |
| Veritasium · least action | targeted | 29,783 | 9,381 | −69% | 9.00 vs 9.00 | 3.0 vs 3.0 | tie |
| Kenji · tomato soup (8:59) | coverage | 8,664 | 5,118 | −41% | 8.00 vs 9.00 | 3.7 vs 4.7 | win |
| Kenji · tomato soup | targeted | 8,664 | 2,904 | −66% | 9.00 vs 8.67 | 3.0 vs 3.0 | **loss** |

Losses ship unedited; per-video raw answers and judge rationales are in [raw/](raw/).

## Instrument validation (Item 2, ran before this evaluation)

- **Two independent annotators** — claude-sonnet-5 and gpt-5.6-terra, zero shared context —
  produced questions, gold evidence spans, and required facts per video *before any pipeline
  ran*. The owner approved model annotators as the substitute for the original two-human
  requirement (2026-07-12); this packet records them as models, not humans. Agreement:
  coverage-span IoU 0.80–0.94 on all five videos; targeted topics coincided on 2/5 (span IoU
  0.73–0.77 where coincident), divergent picks resolved by a fixed alternation rule recorded
  in [raw/frozen_gold.json](raw/frozen_gold.json) (sha256 pinned).
- **Grader repeatability** — three identical re-grades of a fixed answer pair: max
  per-question spread 1 point, unanimous winners ([raw/grader_validation.json](raw/grader_validation.json)).
- **Two instrument defects caught and fixed before this run**: (1) in earlier development
  benchmarks the control's answering agent consumed the raw ASR track while judges graded
  against cleaned captions — here every party consumes the same cleaned track; (2) an
  adversarial probe fully de-anonymized the earlier blinding via key names, filesystem
  co-location, and stylistic fingerprints — here fixtures use randomized neutral keys in an
  isolated directory and judges are restricted to exactly two named files.

## Method

Paired design at the sealed candidate; questions and gold frozen before any pipeline ran;
symmetric answering agents (identical reader rules, self-contained answers); 3 blind judges
per video scoring 1–10 plus gold-required-fact counts; token estimates chars/3.6 + 197/frame
at 512×288. Judge-visible gold facts were custodian-condensed from the frozen gold (whose
hash is recorded); the full annotator files ship in raw/. Reader/grader model for this run:
claude-fable-5 (the registry's sealed epoch fields predate model configuration and were left
as sealed).

## Honest limits

Ten questions across five videos is a real confirmatory sample, not a large one. Judges are
LLMs — validated for repeatability here, but still a model instrument. The duration-split
finding from the development battery (short videos favor the control) was not re-tested
here; all five confirmation videos were ≥8:59 by design, matching the documented guidance.
