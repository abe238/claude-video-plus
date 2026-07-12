# Multi-video development battery — 2026-07-12

4 diverse YouTube videos (tech review, TED talk, short tech news, cooking POV), 12 questions
total (3 per video: 1 coverage + 2 targeted), paired control-vs-evidence answers, graded by 3
blind LLM judges per round with position swap. Headline numbers, straight from
[`results.json`](results.json) `overall`: mean token reduction **80%**, record **5 wins / 2
ties / 5 losses**, mean quality control **8.64** vs evidence **8.58**. Stated plainly: tokens
dropped a lot; overall answer quality was parity, not superiority.

## Measured-commit caveat

This battery measured the evidence compiler at commit **`b90ae21`** (the v0.3.0 pipeline).
v1.0.0 later extended `evidence.py` with retrieval/semantic/state layers, all new behavior
shipped **default-off**. These results describe the development-era compiler, not a v1.0.0
claim.

## Aggregate results

One row per video × question, values verbatim from `results.json`.

| Video | Genre | Duration | Question | Control tokens | Evidence tokens | Reduction | Control quality | Evidence quality | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| Peak Smartphone (MKBHD) | tech review | 13:17 | q1 · coverage | 33,361 | 10,307 | 69% | 8.00 | 9.00 | win |
| Peak Smartphone (MKBHD) | tech review | 13:17 | q2 · targeted | 33,361 | 6,365 | 81% | 7.00 | 9.00 | win |
| Peak Smartphone (MKBHD) | tech review | 13:17 | q3 · targeted | 33,361 | 6,365 | 81% | 8.33 | 9.00 | win |
| Make Stress Your Friend (TED) | talk | 14:29 | q1 · coverage | 31,620 | 10,116 | 68% | 9.00 | 9.00 | tie |
| Make Stress Your Friend (TED) | talk | 14:29 | q2 · targeted | 31,620 | 4,993 | 84% | 9.00 | 9.00 | tie |
| Make Stress Your Friend (TED) | talk | 14:29 | q3 · targeted | 31,620 | 4,993 | 84% | 8.67 | 9.00 | win |
| SQLite Rewrite (Fireship) | short tech news | 5:19 | q1 · coverage | 21,892 | 4,157 | 81% | 9.00 | 8.00 | loss |
| SQLite Rewrite (Fireship) | short tech news | 5:19 | q2 · targeted | 21,892 | 2,581 | 88% | 9.00 | 7.00 | loss |
| SQLite Rewrite (Fireship) | short tech news | 5:19 | q3 · targeted | 21,892 | 2,581 | 88% | 9.00 | 8.00 | loss |
| POV Tteokbokki (Kenji) | cooking POV | 16:11 | q1 · coverage | 32,216 | 9,689 | 70% | 9.00 | 8.33 | loss |
| POV Tteokbokki (Kenji) | cooking POV | 16:11 | q2 · targeted | 32,216 | 5,551 | 83% | 9.00 | 8.67 | loss |
| POV Tteokbokki (Kenji) | cooking POV | 16:11 | q3 · targeted | 32,216 | 5,111 | 84% | 8.67 | 9.00 | win |

## The duration split is the real finding

On the one short video (**<8 min**: SQLite Rewrite, Fireship, 5:19), evidence mode **lost all 3
questions**. Short videos are already cheap for the control (about 21.9k tokens — its full
transcript is small to begin with), so trimming mostly costs quality with little left to save.

On the three videos **≥ 8 min** (MKBHD, TED, Kenji — 9 questions, per `results.json`
`by_duration.videos_8min_plus`), evidence mode went **5 wins / 2 ties / 2 losses**.

Practical guidance: evidence mode earns its keep on longer videos, where the control transcript
is large enough that targeted retrieval has real fat to cut. Prefer the standard (non-evidence)
detail modes on short videos.

## Veritasium: collected but unjudged (excluded)

A 5th video — "The Biggest Misconception in Physics" (Veritasium, `lcjdwSY2AzM`, 27:39, science
explainer) — had both pipelines' answers collected for all questions, but its judge panel was
killed by a session limit before scoring completed. Raw, unscored answers are in
[`raw/lcjdwSY2AzM_unjudged.json`](raw/lcjdwSY2AzM_unjudged.json). This video is **excluded from
every aggregate above** — the `results.json` `videos` array, `overall`, and `by_duration` all
cover only the 4 judged videos.

## Methodology and limitations

- **Paired design**: the control pipeline and the evidence pipeline answer the same question
  against the same video.
- **Symmetric answering agents**: one answering agent per pipeline, identical reader
  instructions — only the evidence each sees differs.
- **Blind judging**: 3 LLM judges per round — one of the three saw the pipeline labels
  position-swapped — scoring 1–10 against the transcript.
- **Ground truth**: the deduplicated caption transcript.
- **Token estimates**: text ≈ chars/3.6; image tokens ≈ 197/frame at the actual 512×288 frame
  size, per Anthropic's published formula.
- **LLM judges are a noisy instrument.** Panel-to-panel variance exists in the raw scores; the
  *paired per-round comparison* (win/tie/loss) is the meaningful number, not the absolute means
  in isolation.
- **Question design bias, disclosed**: questions were written by an agent that had already read
  the transcript, which mildly biases toward answerable questions.
- **This is development data**, not the sealed confirmatory run. The full statistical protocol
  (preregistered margins, family-clustered bootstrap, dev/confirmatory corpus split) is
  specified in [../../plans/V1.0-MASTER-PLAN.md](../../plans/V1.0-MASTER-PLAN.md) and
  [../../execution/v1/MEASUREMENT.md](../../execution/v1/MEASUREMENT.md), and gates any stronger
  public claim.

## Files

- [`results.json`](results.json) — aggregated numbers used throughout this report.
- [`raw/c347oYQO57A.json`](raw/c347oYQO57A.json) — MKBHD, full answers + judge rationales.
- [`raw/RcGyVTAoXEU.json`](raw/RcGyVTAoXEU.json) — TED (Kelly McGonigal), full answers + judge
  rationales.
- [`raw/Sntj4HmuykI.json`](raw/Sntj4HmuykI.json) — Fireship, full answers + judge rationales.
- [`raw/9sfm9aqxygs.json`](raw/9sfm9aqxygs.json) — Kenji Lopez-Alt, full answers + judge
  rationales.
- [`raw/lcjdwSY2AzM_unjudged.json`](raw/lcjdwSY2AzM_unjudged.json) — Veritasium, answers only, no
  judge scores (excluded from aggregates, see above).
