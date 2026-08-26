# v1.5.8 — `--text-anchors` live evidence

Date: 2026-08-25. Absorbed concept: `HUANGCHIHHUNGLeo/claude-real-video@48e1b7c`
(MIT). Reimplemented with hard availability bounds per the Codex gpt-5.6-sol
review (BLOCK → all 6 required changes applied).

## What the feature does

Pins a frame at each transcript-segment start, targeting the measured dedup
blind spot (caption swaps, screen-recording state changes, thin UI text) where a
change is too small for the frame-delta pass to keep. The blind spot itself is
measured by the upstream benchmark cited in `docs/execution/v1/PROVENANCE.md`
(their v0.7.4 before/after); this evidence proves OUR bounded mechanism works
end-to-end on real acquisition.

## Live runs

Source: `https://www.youtube.com/watch?v=WZyRbnpGyzQ` (JFK Rice speech, public,
captioned). Real yt-dlp acquisition + ffmpeg extraction. See "Reliability note"
below on the yt-dlp version used.

| Run | Command (abridged) | Scene frames | Cue frames | Total | Cap |
|---|---|---|---|---|---|
| Default | `--detail balanced --max-frames 20` | 20 | 0 | 20 | 20 |
| Anchored | `… --text-anchors` | 14 | 6 | **20** | 20 |
| Anchored + manual | `… --text-anchors --timestamps 30,600,1000` | 11 | 9 (3 manual + 6 anchor) | **20** | 20 |

Proven properties:
- **Cap respected.** Anchored total is exactly the cap (20); the scene budget is
  reduced by the reserved anchor count (20 → 14), never exceeded.
- **Bounded anchors.** 6 anchors at cap 20 = the exact 30% floor
  (`floor(0.30 × 20) = 6`); `text_anchor_limit()` is the single source of that math.
- **Manual precedence.** With 3 explicit `--timestamps`, all 3 survive; anchors
  consume only the remaining budget (`text_anchor_limit(20, 3) = 6`), so 3 + 6 = 9
  cue frames + 11 scene = 20. No manual timestamp is ever evicted by an anchor.
- **Fail-open / latch.** No-caption sources print a note and run normal
  extraction; evidence mode is latched off (unit-tested), including after an
  evidence→balanced fallback.

Unit + wiring coverage: `tests/test_text_anchors.py` (24 tests) — exact-floor
(incl. huge integer caps) and precedence math, ≤1/sec thinning on unrounded time,
out-of-window/NaN/inf/negative rejection, even-sample cap, hostile-track count +
scan bound, `resolve_text_anchors` orchestration (budget/precedence/fail-open/
error/evidence-off), evidence latch, and a real `--help` registration check.
Full suite: 886 passed.

## Control / gate note

`--text-anchors` is opt-in and default-off, and every change is gated behind
`text_anchors_active`, so it adds no scoring to the default selection path. The
feature-specific control arm proving this is `run-verification.py` ARM A≡B:
default selection and `--text-anchors`-without-captions produce byte-identical
frame selection (see `verify.json`). The flag is therefore additive-only, and the
`83da59f` scoring gate — which governs v2/v3 comparator changes — is satisfied by
construction rather than waived. The v3 comparator work (the actual blind-spot
fix in the default path) is a separate, benchmark-gated track.

## Reliability note (discovered by the yt-dlp acquisition battery)

The installed **yt-dlp 2026.07.04 returns HTTP 403 on every YouTube media
download today** (metadata extraction still succeeds; the streaming URLs it
generates are rejected by googlevideo). **yt-dlp 2026.08.19 downloads fine.** The
live runs above therefore used the current yt-dlp via `python -m yt_dlp`.

This is a live, environment-level reliability incident affecting anyone on the
~52-day-old build. **Folded into this release** (owner decision): the 403
media-download failure was reported as `acquisition failed: unknown` because the
multi-strategy retry loop surfaced the last attempt's `unknown` and masked the
first attempt's `http_403`. Acquisition now reports the most informative failure
across attempts and attaches an actionable "upgrade yt-dlp" remediation for
403/SABR/format-gone (source-neutral). Verified live: `unknown` → `http_403 --
… pip install -U yt-dlp …`. Regression tests in `tests/test_acquisition.py`.

Not changed here: the staleness guard's 120-day warn threshold (age is a weaker
signal than the actual download failure, which now self-describes) — noted for a
possible later pass, not required by this fix.
