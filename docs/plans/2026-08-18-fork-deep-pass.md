# Fork deep-pass: incorporation plan (2026-08-18)

Line-by-line pass over the four deep-queue forks surfaced by the radar-v2 full
sweep. Verdict per fork, then a ranked incorporation plan. Reviewed by Codex
gpt-5.6-sol before any implementation.

## Verdicts

### 1. yotamleo/claude-video (HIMMEL-868) — CROSS-CHECK COMPLETE, nothing to port

They ran their own audit of upstream's open PRs (#63, #45, #42, #28, #14, #1)
and adopted a curated set. Cross-checked their entire ADOPT list against our
tree:

| their adoption | ours |
|---|---|
| #63 `-vsync`→`-fps_mode`, console output | v1.3.5, with the 5.1 capability probe theirs lacks |
| #45 NTFS ACL via icacls | v1.3.6, via Get-Acl + well-known SIDs (locale-safe; theirs is English-name-fragile) |
| #42 YouTube player-client fallback | `WATCH_YOUTUBE_CLIENTS` (validated, 1–3 safe names) |
| #14 `python -m yt_dlp` PATH fallback | v1.3.6, probed + cached |
| #28 1998px clamp | present (`_scale_filter`, both edges) |

Their ADOPT set is a strict subset of what we ship. Value extracted: an
independent audit CONFIRMS our absorption of the upstream PR backlog is
complete as of their audit date. Their method (PR-stream mining) is now our
radar's `scan_prs`.

### 2. vcolombo/claude-video (v0.3.x) — ONE REAL GAP FOUND IN OURS

Mostly parallel evolution (untrusted-content boundary, keys-out-of-band,
proxy support ~= our cookie/client machinery, CI suite). Two extractions:

- **Transcription cost bound — THEIR MECHANISM IS BETTER THAN OURS.**
  Verified against our tree: we cap per-chunk bytes (`MAX_UPLOAD_BYTES`) but
  place NO bound on chunk count or total uploaded audio. A caption-less
  10-hour source with cloud consent uploads unbounded chunks at API cost.
  Theirs: `MAX_CHUNKS = 24` + a total-bytes cap, refusing with actionable
  guidance ("use --start/--end to transcribe a section, or rely on captions").
  **PLAN ITEM P1.**
- **CI action SHA-pinning** (`actions/checkout@<sha>` vs our `@v4` tags):
  small supply-chain hardening. **PLAN ITEM P3.**

### 3. m1crodevil/hermes-video (+90, ★4) — DIVERGED PRODUCT; one opt-in idea

A rewrite into an auto-"comprehensive analysis" product (moments.py,
synthesis.py, models.py) — different mission; their analysis pipeline
overlaps our structural mode but moves intelligence from SKILL.md into
Python, which we deliberately do not do. Extractions considered:

- **Content-addressed video cache** (`~/.cache/watch/<sha256>.mp4`, 10 GB
  LRU): directly conflicts with our no-media-persistence posture
  (`media_persistence_forbidden`, 24 h work-dir pruning) — but has real value
  for repeat-analysis of the same video across sessions. Verdict: viable ONLY
  as explicit opt-in (`WATCH_VIDEO_CACHE=1`), owner-only storage rules like
  the evidence cache, prune tooling included. **PLAN ITEM P2 (opt-in,
  benchmark-free: it changes cost, not selection quality).**
- 2s-section re-downloads for moment re-runs: superseded by our 24 h work-dir
  retention + local-file re-run flow. Skip.

### 4. EmilyYoung71415/claude-video continuation — parallel evolution

Permission-before-download = our v1.3.0 consent (originally credited to this
same author). WAV chunks for local whisper: our adapter chain already feeds
adapters their preferred format per adapter contract. `.scratch/` PRD/ticket
conventions are their workflow, not runtime. Nothing to port; keep watching —
this fork originates good safety ideas.

## Ranked plan (each item independently shippable, Codex-gated)

- **P1 — Transcription cost bound (from vcolombo).** `MAX_CHUNKS` (default 24)
  + total-audio-bytes cap in `plan_chunks`/callers; refusal message routes to
  `--start`/`--end` or captions; env knob for the bound; tests: at-bound,
  over-bound refusal text, env override, and the existing chunk paths
  unaffected. No benchmark gate needed (bounds cost; selection untouched)
  but verify the refusal composes with our fail-open transcript contract
  (frames-only degrade, never a dead run).
- **P2 — Opt-in content-addressed video cache (from hermes-video).** Off by
  default; `WATCH_VIDEO_CACHE=1` enables; sha256 keying; LRU bound
  (`WATCH_VIDEO_CACHE_GB`, default 5); owner-only dir rules mirroring
  `state.py` (incl. the Windows profile-root guard); `lifecycle.py --purge-cache`
  covers it; SKILL.md privacy section gains one line. Larger item — needs its
  own session.
- **P3 — CI action SHA-pinning (from vcolombo).** Pin `actions/checkout` and
  `actions/setup-python` to full SHAs with version comments in both
  workflows. Trivial.

Explicitly NOT planned: hermes-video's auto-analysis pipeline (mission
conflict), their models.py LLM layer (intelligence stays in SKILL.md),
yotamleo items (subset), EmilyYoung items (parallel).
