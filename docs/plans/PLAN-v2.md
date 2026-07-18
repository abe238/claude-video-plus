# claude-video-plus competitive absorption plan — v2 (post Codex high-effort review, REDO applied)

Repo: `~/Documents/Github/claude-video-plus` (v1.0.7, 400 tests green). Date: 2026-07-18.
v1 → v2 delta: applied all 8 Codex amendments. Scope cut from 4 releases to 2 releases + one measurement track. Already shipped out-of-band: the injection-hardening fixture page + field survey (was D2's demo half; commit 7c58f90).

## Context (unchanged, verified by 4 code-reading agents)

Upstream has zero commits past our fork point (merge-base = v0.2.0 = HEAD = `83da59f`). claude-real-video (1.7k★) leads us narrowly in frame selection (density floor, window dedup, RGB comparator) and trails us structurally on token cost (no retrieval; loudest HN complaint). video-vision (1k★) contributes VAD/checksum ideas. claude-watch contributes word timestamps. Only we + claude-real-video harden media text; ours covers 5 surfaces loosely-matched, theirs 1 surface exact-match.

## Invariants (repo rules, apply to every item)

- Any change to selection behavior (A1, A2, A3, A5) or reader-visible evidence (A4 if ever) is gated on the frozen-control benchmark vs `83da59f` via the repo's own `tools/control_harness.py` + `docs/execution/v1/MEASUREMENT.md` machinery. Ablate per-item, then combined.
- Every new media-derived or model-derived string passes `sanitize_for_report` with a test per surface.
- Version sync across SKILL.md + both plugin.json; no versions/test-counts in README or docs pages (guard test enforces).
- Local-first: nothing new transmits without explicit opt-in; new deps are detect-don't-install, fail-open.
- 2fps default cap semantics unchanged unless the user explicitly opts out.
- Attribution: prior-art credit per adopted idea in CHANGELOG (claude-real-video, video-vision, claude-watch, upstream PR authors). No verbatim MIT code.
- Consent mechanisms must be harness-neutral (CLI flag / config), never AskUserQuestion-dependent (works on Codex/Cursor/Copilot too).

## Track M — measurement protocol (starts first; runs comparisons LAST)

- **M1. Protocol freeze (before any Release-1 code).** Preregister in `docs/benchmarks/2026-07-bakeoff/PROTOCOL.md`: corpus (≥8 videos across talk/screencast/fast-cut/music, pinned URLs + caption hashes), question families (questions from the same video treated as dependent; family-clustered analysis), frozen answer keys, judge design (≥2 judges, randomized opaque arm labels, blinded to fork/config/cost, frozen prompts + model epochs), paired execution order, per-fork command/config/dependency disclosure, competitor commit SHAs pinned, failure/exclusion rules, provider-reported tokens separated from estimates, primary comparison predeclared (default-user behavior, not matched-budget), and the repo's deterministic 10,000-resample family bootstrap with a preregistered minimum family count — below it, results are labeled descriptive and no superiority claims are made. Logs published checksummed and deterministically redacted (repo machinery refuses secrets/private paths by design).
- **M2. Harness scaffolding (parallel with Release 1).** `bench/bakeoff/` runners for {ours, upstream `83da59f`, claude-real-video @pinned SHA, video-vision @pinned SHA}. Runner contract: given (video, question) → (answer, tokens-delivered, wall time, artifact log). Competitors run at their documented defaults; their configs disclosed; runner-correction PRs accepted.
- **M3. Ablations + comparative run (AFTER Release 1 tags).** First isolated A1/A2/A3/A5 ablations vs control `83da59f`; then pin "ours" to the release commit + config hash; then the cross-fork comparative run. Results land dated in `docs/benchmarks/`, linked from stable pages. No public superiority language before this gate passes.
- Sizing: L/XL. ~2–3 sessions total, M3 blocked on Release 1.

## Release 1 — v1.1.0 "frame engine" (selection changes; all benchmark-gated)

- **R1a. Comparator rebuild first (was A3, M).** Replace `_frame_delta` grayscale-mean with RGB max-channel changed-cell %: thumbnails `rgb24` at 16×16, cell counts toward "changed" when max-channel delta > tolerance; frame kept when changed-cell % > threshold. Spec pins: thumbnail dims, tolerance, threshold, JPEG-stable synthetic fixtures. **Explicit test migration:** the mean-diff/grayscale/inclusive-threshold expectations in `tests/test_dedup.py` are rewritten, not preserved. Accept: equal-luma red→green kept; caption-swap kept; grain-only dropped; ablation vs control shows no answer-quality regression.
- **R1b. Sliding-window dedup (was A2, S).** Window of last N=4 kept thumbnails with a time horizon T (a return to scene A *outside* T is kept even if similar — a semantically meaningful return must not be discarded forever). Defaults N=4, T=90s; both tunable. **Test migration named:** `test_dedupe_keeps_all_distinct` (A→B→A→B currently expects zero drops) is rewritten to the new contract. Accept: A-B-A within T drops second A; A…(>T)…A keeps both; deletion/reindex/fail-open behavior specified.
- **R1c. Density floor (was A1, S).** Floor frames must survive dedup: implement as *pinned* floor candidates (exempt from dedup eviction) OR as a post-dedup maximum-gap invariant — decide by ablation, spec the chosen one. Accept: synthetic 10-min static video with 2 cuts → no inter-frame gap exceeds floor interval after dedup; budgets unchanged on normal videos.
- **R1d. `--fps` cap opt-out (was A5, S).** Explicit `--fps > 2` lifts the clamp; nonpositive fps rejected; without the flag, selected timestamps byte-identical to today; output count never exceeds the active cap; identical behavior via `watch.py` and standalone `frames.py` (their fps handling currently differs — unify). Benchmark-gated (it changes selection).
- Ship: full suite + migrated tests, version sync, tag, verify published artifact, changelog credits (claude-real-video prior art for R1a–R1c; upstream PR #60/#37 for R1d).
- Sizing: 1.5–2 sessions.

## Release 2 — v1.2.0 "transcript correctness + durable evidence"

- **R2a. VAD gate for whisper-cli (was B1, L — the big one).** Scope pinned: our own pinned Silero model download to our cache (0600 perms, SHA-256 verified from a pinned constant, offline = skip gate, fail-open to non-VAD behavior), macOS+Linux. **Contract change named:** a genuinely silent input must yield a terminal `no_speech` result — today `TranscriptResult` forbids empty success and `_run_chunked` treats zero segments as "unavailable" and falls through to the next adapter (which would re-hallucinate). Add a `no_speech` terminal state honored by the pipeline. Accept: silent clip → `no_speech`, no adapter fall-through, no fabricated text; VAD gated on false-negative speech fixtures (quiet speech kept) and WER-neutral on normal clips.
- **R2b. Word-level timestamps (was B3, M/L).** `words[]` added to `TranscriptSegment` (absent-tolerant), nested timestamp shifting for chunk offsets, `segments_from_response` + every adapter covered, **receipt schema/key bumped** so old segment-only receipts cannot mask the feature. Fail-open when backend lacks support. Accept: focused run yields per-word starts on supporting backends; receipts round-trip words; stale receipts invalidated.
- **R2c. Silence-chunking delta (was B4, M).** Not greenfield — `transcription_chunks.py` already snaps cuts to silence. The delta only: tight→loose threshold fallback (-35dB/0.40s → -30dB/0.2s), `hard_cut` classification when neither finds silence, warnings propagated to the report, continuity/offset invariants asserted. Accept: no-silence synthetic chunks with `hard_cut` warning; normal audio byte-identical chunk boundaries.
- **R2d. Media-rich portable bundles (was C1, S — reframed).** NOT a new schema: extend `portable.py`'s existing `export_bundle` with `include_media=True` (frames + transcript + timeline into the existing schema-versioned, checksummed, relative-path bundle). Accept: export → verify → replay round-trip; every replayed frame reference resolves; no absolute paths/secrets; new text surfaces sanitized; `tests/test_portable.py` extended.
- Cut from this release (Codex #3/#6): ~~B2 model checksums~~ (whisper-cli manages its own models; we won't take ownership of its cache), ~~B5 --keep-audio~~, ~~C2 vault ingest~~ (returns only with harness-neutral CLI consent design), ~~C3 audio pre-pass~~, ~~C4 Windows~~ (needs Windows CI to be honest — backlog), ~~A4 grids~~ (needs a readability/answer-quality gate — backlog).
- Sizing: 1.5–2 sessions.

## Backlog (explicitly deferred, with re-entry condition)

A4 contact-sheet grids (re-enter with quality gate + deterministic tile spec) · C2 vault ingest (CLI/config consent, cross-host) · C3 structural audio signals (with evidence-quality fixtures) · C4 Windows UTF-8 (with Windows CI leg) · B2 model ownership · settled-local dedup channel (decide from R1a ablation data) · cloud audio-tags · descriptions-mode offload · --hook/pacing.

## Risks (updated)

1. R1 test migration touches the dedup suite's core contracts — migrate tests in the same commit as behavior, per item, never batch.
2. M3 fairness disputes — mitigated by preregistration, pinned SHAs, disclosed configs, correction PRs, family-clustered stats, descriptive-only labeling under the minimum-N.
3. R2a's `no_speech` terminal state touches the adapter pipeline contract — one focused contract test per adapter before wiring.
4. Budget: 2 releases + M ≈ 5–7 sessions realistic total. If squeezed: R1 ships without R1d; R2 ships as R2a+R2c only; M1/M2 never cut (they gate all public claims).
