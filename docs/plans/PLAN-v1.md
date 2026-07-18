# claude-video-plus competitive absorption plan (draft v1)

Repo: `~/Documents/Github/claude-video-plus` (abe238/claude-video-plus, currently v1.0.7, 400 tests green).
Date: 2026-07-18. Author: Fable 5 session, from 4 parallel deep-read agents (upstream + 5 competitor repos, code-verified, not README-trusted).

## Context

- Upstream `bradautomates/claude-video` (9.1k★) has shipped **zero commits** past our fork point (merge-base = v0.2.0 tag = upstream HEAD = `83da59f`, verified 3 ways). All signal is in 45 unmerged community PRs, nearly all of which we already exceed.
- `HUANGCHIHHUNGLeo/claude-real-video` (1.7k★, HN front page) beat us to the "scene-aware + dedup + local" story. Its frame engine is ahead of ours in 2 narrow, cheap-to-close places. Its loudest HN complaint is token cost — the exact thing our evidence mode solves and it structurally cannot (no retrieval; ships all frames + full transcript every run).
- `jordanrendric/claude-video-vision` (1k★) is real engineering (audio-event tags, VAD, checksums) with **no injection hardening at all** on attacker-controlled media text.
- `taoufik123-collab/claude-watch` has word-level Whisper timestamps (a genuine gap of ours) and a proven-demand Obsidian ingest flow.
- Nobody else in the field sanitizes media-derived text. We are alone on that property.

## Goals

1. Close the measurable frame-engine gaps vs claude-real-video (they are S/M effort).
2. Add the 3 genuine capability gaps found across the field (word timestamps, VAD gating, model checksums).
3. Ship the empirical-positioning artifact: a reproducible cross-fork bake-off harness whose losses we publish.
4. Preserve every hard invariant: 2fps default cap semantics, local-first transcription, untrusted-media sanitization on every new text surface, benchmark-gating of selection changes against control `83da59f` (AGENTS.md rule).

## Non-goals (explicit rejects, with source)

- Speaker diarization, `--viewer`, web servers, `--export llc` (claude-real-video) — scope creep.
- PyPI distribution parity — we are agent-native; noted, not chased.
- New cloud transcription providers (Deepgram/AssemblyAI/TwelveLabs, upstream PRs) — violates local-first thesis.
- Blur/exposure per-frame stats (video-vision) — no Q&A evidence value.
- Regressing to manual "analyze then hand-pick segments" workflow (video-vision) — our retrieval automates it.
- Copying MIT code verbatim from claude-real-video — reimplement ideas; credit as prior art in CHANGELOG.

## Work items

### Release A — v1.1.0 "frame engine parity+" (all in frames.py; benchmark-gated)

- **A1. Density floor in scene selection (S).** Today a slow screencast with ≥8 sparse scene cuts can leave multi-minute stretches with zero frames. Add a floor term to the single-pass ffmpeg select expression (`+not(mod(n,every_n))`), one pass so dedup still sees chronological neighbors, bounded by existing frame budgets. Accept: synthetic 10-min static-with-2-cuts video gets ≥1 frame per floor interval; budgets unchanged on normal videos.
- **A2. Sliding-window dedup (S).** `_dedupe_by_deltas` compares only against last kept frame; A→B→A cutaways re-send A. Keep window of last N=4 kept thumbnails, drop frame if similar to ANY. Accept: A-B-A synthetic test drops the second A; existing dedup tests still pass.
- **A3. RGB max-channel dedup comparator (M).** Current grayscale mean-diff is blind to equal-luma color cuts and to small text/caption changes (they average to ~0). Move thumbnails to rgb24; score = % of cells whose max-channel delta exceeds tolerance. Accept: red→green equal-luma synthetic is kept as distinct; caption-swap synthetic is kept; grain-only synthetic is still dropped.
- **A4. Contact-sheet grids `--grid` (S).** Tile frames 3×3 into composite JPEGs (~9× fewer Read calls). Opt-in flag; report lists per-tile timestamps. HN-validated ("frames in a grid… did surprisingly well").
- **A5. `--fps` cap opt-out (S).** Upstream's most-requested capability (PR #60, issue #37): explicit `--fps` above 2 lifts the clamp for short/fast-action clips, guarded by the frame-budget cap so long videos cannot explode. Default behavior unchanged.
- **Gate for A1–A3:** run the repo's frozen benchmark harness against control `83da59f` before claiming improvement (AGENTS.md hard rule). If quality regresses, the item ships behind a flag or not at all.

### Release B — v1.2.0 "transcript correctness"

- **B1. Silero VAD gate for whisper-cli (S).** Stops Whisper hallucinating text on silence/music — a correctness fix AND an injection-surface reduction. Checksum the VAD model download. Accept: silent 5s clip yields empty transcript, not fabricated text.
- **B2. Whisper model SHA-256 verification (S).** Supply-chain integrity for any model file we download. Accept: corrupted file is rejected with a clear error.
- **B3. Word-level Whisper timestamps (S).** `verbose_json` + word granularity where the backend supports it (Groq/OpenAI param; whisper-cli `--word_timestamps`); thread `words[]` through segments. Enables frame×word alignment in focus ranges. Accept: focused run on a captioned-off clip yields per-word starts; report unchanged when unavailable (fail-open).
- **B4. Two-pass silence chunking + hard-cut warnings (S).** Our chunker is single-threshold; adopt tight→loose fallback and surface `hard_cut` warnings. Accept: synthetic no-silence audio chunks with warning; normal audio unchanged.
- **B5. `--keep-audio` (S).** Persist extracted audio for audio-native follow-ups. Trivial.

### Release C — v1.3.0 "durable evidence & reach"

- **C1. `--evidence-dir` durable export (M).** Portable bundle: frames + transcript + timeline + schema-versioned index.json (upstream PR #79 demand). This is also the substrate for C2. Accept: bundle re-opens standalone; paths relative; media-text inside is sanitized.
- **C2. Obsidian/vault auto-ingest (M).** Consent-gated: resolve `$WATCH_VAULT_DIR`, stage report+hero frames into `vault/raw/watched/<slug>/`, open via obsidian:// URL. Proven demand (Toufik workflow, featured on TNNT). Accept: no vault → silently skipped; never writes without explicit AskUserQuestion consent.
- **C3. Structural audio pre-pass as retrieval signal (S).** Cheap ffmpeg ebur128 loudness + black/freeze detection feeding evidence-mode chapter boundaries ("music bed 00:12–00:40"). Coarse local tier only; cloud audio-tags deferred. All derived strings sanitized.
- **C4. Windows stdout UTF-8 reconfigure (S).** One-liner; kills the largest upstream PR cluster (8 dupes).

### Release D — the positioning artifact (parallel track)

- **D1. Cross-fork bake-off harness (M/L).** `bench/bakeoff/`: N pinned videos (mixed: talk, screencast, fast-cut, music-heavy), M pre-registered questions with frozen answer keys, runners for {ours, upstream v0.2.0, claude-real-video, video-vision}, measuring (a) tokens delivered to the model, (b) answer accuracy vs key via blind judge, (c) wall time. Publish ALL numbers including losses, unedited. Accept: `python bench/bakeoff/run.py --fork ours` reproduces our row end-to-end on a clean machine; README table links raw logs; competitors can PR corrections to their own runner.
- **D2. 30-second verifiable demos in README (S).** The 1/13→13/13 spelling demo command; a hostile-description fixture showing sanitization neutralize it live.

### Deferred backlog (explicitly not now)

- Cloud audio-event tags (video-vision tier-b), descriptions-mode frame→text offload for very long videos, `--hook` first-10s mode + pacing metrics, Fathom cookie-file support, settled-local 192px dedup channel (L; study after A3 benchmark data).

## Sequencing & effort

D1 starts first (it gates all "empirically better" claims and takes longest), A and B execute in parallel worktrees, C after A/B land. Every release: full pytest suite, version sync across 3 files, tag → CI builds watch.skill, verify published artifact by download+run (established pipeline). Rough effort: A ≈ 1 session, B ≈ 1 session, C ≈ 1–1.5 sessions, D ≈ 1.5–2 sessions.

## Risks

1. A3 (comparator rebuild) can regress frame selection subtly → mitigated by the frozen-control benchmark gate; ship behind flag if inconclusive.
2. Bake-off fairness disputes → mitigate by pinning competitor versions, publishing their invocation configs, accepting runner-correction PRs.
3. New text surfaces (C3 tags, C1 bundle, D1 judge outputs) each widen the injection surface → hard rule: every new media-derived or model-derived string passes `sanitize_for_report` before entering any report; test per surface.
4. whisper-at / VAD deps may not install cleanly on all platforms → all new audio machinery is detect-don't-install, fail-open like existing adapters.
5. Scope: 4 releases is a lot → each release independently shippable; cutting C or halving D degrades gracefully.

## Attribution

CHANGELOG credits per adopted idea: claude-real-video (density floor, window dedup, RGB comparator, grids — prior art), video-vision (VAD, checksums, silence chunking), claude-watch (word timestamps, vault ingest), upstream PRs #60/#79 authors. No verbatim MIT code copied.
