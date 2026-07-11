# Single-video deep-dive — 2026-07-11

**Video**: "AI News: GPT-5.6 and the new Super App are a Massive Leap!" (Matt Wolfe,
38:40, 1080p, English auto-captions, 18 native chapters). YouTube ID `EOCRtSnvNNE`.

**Questions** (one per class):
- Q1 coverage: "Summarize this video — what are the main stories and announcements covered?"
- Q2 targeted + hype-exclusion: "What's actually new with GPT-5.6 — capabilities, speed, cost — skip the hype?"
- Q3 targeted: "What is the new Super App and what does it do?"

## Final result (round 5)

| Q | Control tokens | Evidence tokens | Δ | Control quality | Evidence quality | Verdict |
|---|---|---|---|---|---|---|
| Q1 | 50,941 | 20,148 | −60% | 8.33 | **9.33** | win |
| Q2 | 50,941 | 11,505 | −77% | 9.00 | 9.00 | tie |
| Q3 | 50,941 | 10,555 | −79% | 8.33 | **9.33** | win |

Control = original pipeline, `balanced` mode (100 frames + full raw transcript).
Quality = mean of 3 blind judges, 1–10, position-swapped panel.

## The iteration story (why the rounds matter)

- **Round 0** (`round0_*.json`): a naive tf-idf retrieval candidate saved 91% of tokens
  and **lost 3–0** — it missed the pricing segment on a cost question, missed the Sites
  feature and Work-mode demo on the super-app question, and repeated a presenter
  misstatement. Kept in this packet as the honest baseline.
- **Rounds 1–3**: built the shipped compiler — chapter roll-up, numeric guard (+frame at
  each guarded span), facet sufficiency, span rescue, transcript dedup, budget governor.
  Round 3: Q1/Q3 wins, Q2 still trailing.
- **Round 4**: judges revealed the Q2 gap was reader behavior, not evidence — the
  pricing-page frame was in evidence but not being mined. Added the frame-mining
  instruction to SKILL.md.
- **Round 5** (`final_candidate_answers.json`): added the reconcile-conflicting-claims
  instruction; judges credited the evidence pipeline for catching the presenter's
  Terra-vs-Luna pricing self-contradiction that the control repeated. Q2 → tie.

## Files

- `control_token_accounting.json` — control-mode measurements (transcript/efficient/balanced) + candidate v1
- `round0_answers_control_and_candidate_v1.json` — both pipelines' full answers, round 0
- `round0_judge_scores.json` — round-0 normalized judge scores (the 3–0 loss)
- `candidate_evidence_manifest_q2_example.json` — a real evidence manifest (Q2, round 3): every selection with timestamp, reason, score
- `final_candidate_answers.json` — the round-5 evidence-pipeline answers judged above
