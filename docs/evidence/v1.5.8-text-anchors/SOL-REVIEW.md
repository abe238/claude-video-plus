# SOL-REVIEW — v1.5.8 (`--text-anchors` + yt-dlp 403 remediation)

Adversarial reviewer: Codex `gpt-5.6-sol`, `model_reasoning_effort=xhigh`,
`--sandbox read-only`. Two-axis (Standards / Spec) review, watchdog-guarded.

## Round 0 — plan review (before implementation)

Verdict: **APPROVE-WITH-CHANGES**. Confirmed the dedup blind spot is real in both
our v1 default and v2 engines; established the crux that candidate SUPPLY (our
~30s floor) — not just the dedup decision — is what a full fix needs (deferred to
the separate v3 track). Accepted `--text-anchors` as a bounded, own-release
change. Corrected two of our own errors: the "no-persistence posture" rationale
(we already ship an opt-in cache) and a missed upstream mechanism (v0.7.16 action
channel, logged for the v3 corpus).

## Round 1 — implementation review

Verdict: **BLOCK**, 6 required changes:
1. Hostile-VTT memory bound — the cap was applied after O(N) allocations.
2. Explicit `--timestamps` precedence — a union+even-sample could evict a manual cue.
3. Exact 30% floor — `max(1, …)` emitted an anchor for caps 1–3 where floor is 0.
4. Evidence-mode latch — an evidence→balanced fallback re-enabled the flag.
5. Contract wording — "cue starts" vs post-normalization transcript segments.
6. Tests/SKILL/provenance/report — orchestration untested; SKILL didn't expose the flag.

Disposition: all 6 applied. Single-pass O(kept) thinning + a 200k scan bound;
`text_anchor_limit()` gives manual precedence + exact floor; `text_anchors_enabled()`
latch captured before the evidence branch; wording changed to "transcript-segment";
`resolve_text_anchors()` extracted as a pure fn and unit-tested (budget, precedence,
fail-open, evidence-off); SKILL gated list exposes the flag; PROVENANCE rows added.

## Round 2 — re-review

Verdict: **BLOCK** (core algorithm accepted; completion/rigor items):
- Spec 3 — `int(0.30*max_frames)` is float, wrong for huge integer caps → switched
  to `(3*max_frames)//10` with a large-integer regression.
- Spec 1/2/5 — corrected the memory comment (O(kept), cap applied after), the
  precedence comment (manual-alone-over-cap still even-samples), and the residual
  "subtitle-cue" wording in CLI help + flags.md heading.
- Spec 6 — added pure-function orchestration tests; P2 rename `anchor_budget` →
  `text_anchor_limit` (avoids clash with the domain "Evidence budget").
- Standards 1 — feature-specific `83da59f`-class arm produced: this harness proves
  the flag is additive-only (flag-off ≡ flag-on-without-captions, identical frame
  selection), so the default scoring path is untouched by construction.
- Standards 2 — this evidence packet (`verify.json`, `SOL-REVIEW.md`, `EXIT.md`,
  live trace) added.
- Standards 3 — CHANGELOG 1.5.8 entry added; provenance credit now truthful.

## yt-dlp finding (folded into this release by owner decision)

The battery surfaced a live incident: installed yt-dlp 2026.07.04 returns HTTP
403 on all YouTube media downloads; 2026.08.19 works. Root-caused a masking bug —
the multi-strategy retry loop reported the LAST attempt's `unknown` instead of
the first attempt's `http_403`. Fixed to surface the most informative failure,
plus an actionable "upgrade yt-dlp" remediation for 403/SABR/format-gone. Both
regression-tested; verified live (message changed from `unknown` to `http_403 --
… pip install -U yt-dlp …`).
