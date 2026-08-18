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

Their ADOPT set is a strict subset of what we ship. Scope of the claim
(Codex-corrected): this confirms coverage of THEIR AUDITED LIST
(#63/#45/#42/#28/#14/#1, inspected at their `himmel-main` head, 2026-08-18) —
not of the entire 154-PR upstream backlog. The new PR-stream radar covers
future arrivals; the historical remainder is unaudited by anyone. Their method (PR-stream mining) is now our
radar's `scan_prs`.

### 2. vcolombo/claude-video (v0.3.x) — ONE REAL GAP FOUND IN OURS

Mostly parallel evolution (untrusted-content boundary, keys-out-of-band,
CI suite). Their proxy support is NOT claimed equivalent to our
cookie/client machinery (Codex-corrected: network routing vs
extraction/authentication are different layers); we simply have no proxy
feature and no recorded demand for one — skip on demand, not on equivalence. Two extractions:

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
  the evidence cache, prune tooling included. **PLAN ITEM P2** (see the
  Codex-hardened constraint set below — incl. proven byte-identity and
  cold/hit measurement).
- 2s-section re-downloads for moment re-runs: NOT superseded for cold/first
  runs (Codex-corrected — our 24 h retention only helps once a full download
  exists; theirs avoids the full download entirely on targeted re-runs).
  Verdict upgraded skip → EVALUATE: measure section-download vs full-download
  cost on a focused `--start/--end` first run before judging. **PLAN ITEM P4
  (evaluate-only, benchmark-gated).**

### 4. EmilyYoung71415/claude-video continuation — parallel evolution

Permission-before-download = our v1.3.0 consent (originally credited to this
same author). WAV chunks for local whisper: Codex-corrected — our shared
preparation path emits 64-kbps MP3 for EVERY adapter (an accepted shared
format, not per-adapter preference); whether WAV measurably helps local
whisper accuracy/latency is untested. Folded into P4's evaluation scope. `.scratch/` PRD/ticket
conventions are their workflow, not runtime. Nothing to port; keep watching —
this fork originates good safety ideas.

## Ranked plan (each item independently shippable, Codex-gated)

- **P1 — REMOTE transcription cost bound (from vcolombo; Codex-hardened).**
  Applies to remote adapters ONLY — local transcription is never capped.
  Bounds CUMULATIVE uploaded bytes/duration and request attempts (retries and
  Groq→OpenAI fallback included), not merely prepared chunk count. On the
  bound: structured `remote_cost_limit_exceeded`, all further remote fallback
  stops, the run degrades to frames-only SUCCESS (exit 0), and the report
  carries the `--start`/`--end` guidance. Tests: captions/local unaffected,
  zero remote calls past the bound, exact-bound acceptance, focused-range
  acceptance, retry/fallback accounting, final exit 0.
- **P2 — Opt-in content-addressed video cache (from hermes-video;
  Codex-hardened constraint set).** A SEPARATE opt-in media store —
  `EvidenceState`'s unconditional media refusal is never weakened. Required
  design elements before any code: source-index → verified-content-digest
  lookup (a true digest is unknowable pre-download; `source_identity()` is
  NOT reusable unchanged — query-form YouTube URLs currently collapse to one
  `/watch` identity); URL-only scope (local files never duplicated);
  cookie-authenticated/signed/private sources excluded or double-consented;
  per-hit checksum verification; owner/ACL rules incl. the Windows
  profile-root guard; no symlinks; atomic writes + locking; corrupt-entry
  eviction; per-entry max + total LRU bound + TTL + disk-headroom guard +
  oversized bypass; consent and `WATCH_MAX_FILESIZE` semantics on misses;
  fail-open to fresh download on ANY cache failure; purge/uninstall/inspect
  tooling and privacy docs. Acceptance: cache-hit bytes PROVEN identical,
  cold/hit measurement, end-to-end output equivalence. Own session, own gate.
- **P3 — CI action SHA-pinning (from vcolombo; Codex-widened).** Pin EVERY
  external action in BOTH workflows — including the privileged
  `softprops/action-gh-release` — to full immutable SHAs with version
  comments; add a test asserting every `uses:` is a 40-hex SHA; note
  Dependabot/renovate for update PRs.
- **P4 — Evaluate (benchmark-gated, from hermes-video + EmilyYoung):**
  (a) section-download vs full-download cost for focused first runs;
  (b) WAV vs 64-kbps MP3 for local-whisper accuracy/latency. Measurement
  first; no port without numbers.

Explicitly NOT planned: hermes-video's auto-analysis pipeline (mission
conflict), their models.py LLM layer (intelligence stays in SKILL.md),
yotamleo items (subset), EmilyYoung items (parallel).
