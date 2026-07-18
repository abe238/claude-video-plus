# claude-video-plus competitive absorption plan — v3 FINAL
# (v1 → Codex high-effort REDO applied → v2 → Fable adversarial pass applied)

Repo: `~/Documents/Github/claude-video-plus` (v1.0.7, 400 tests green). Date: 2026-07-18.
Already shipped out-of-band: injection-hardening fixture page + field survey + SECURITY.md (commit 7c58f90).

## Invariants (unchanged from v2)

Benchmark-gate all selection-behavior changes vs frozen control `83da59f` (repo harness). Sanitize every new text surface, with a test. Version sync; no versions in docs (guard test). Local-first; detect-don't-install; fail-open. Harness-neutral consent (CLI/config, never AskUserQuestion). Prior-art credit per adopted idea; no verbatim MIT code. Contract-tests-first (red) before each behavior change.

## Track M — measurement (protocol first; public runs last)

- **M0. Calibration run (internal, unpublished).** Run the harness skeleton against CURRENT code on 2–3 videos to shake out runner bugs before anything is frozen. If any corpus video fails our own pipeline, fix before M1 freeze.
- **M1. Protocol freeze.** `docs/benchmarks/2026-07-bakeoff/PROTOCOL.md`, preregistered: corpus ≥8 **captioned** videos (talk/screencast/fast-cut/music; pinned URLs + caption hashes) — transcription variance is EXCLUDED from the primary estimand and said so openly; a separate exploratory transcription track may follow. Question families **stratified by type (targeted / summary / visual / numeric)**, including families where we expect to lose; questions within a video are dependent → family-clustered analysis; frozen answer keys. ≥2 judges, randomized opaque arm labels, blinded to fork/config/cost, frozen prompts + model epochs, paired execution order. Competitor commit SHAs pinned; runners use **documented defaults only** (competitor-suggested alternates shown as separate labeled rows via PR). Failure/exclusion rules predeclared. Provider-reported tokens separated from estimates. Primary comparison predeclared: default-user behavior. Repo's deterministic 10,000-resample family bootstrap; below the preregistered minimum family count, results are labeled descriptive and no superiority claims are made. Secondary metrics (wall time) reported even where we lose. Logs published checksummed + deterministically redacted.
- **M2. Runners** for {ours @pinned, upstream `83da59f`, claude-real-video @pinned, video-vision @pinned}: (video, question) → (answer, tokens delivered, wall time, artifact log).
- **M3. Ablations + comparative run — AFTER Release 1 tags.** Per-mechanism ablations (comparator / window / floor / fps) from one run matrix vs control; then pin ours to release commit + config hash; then the cross-fork run. Dated results in `docs/benchmarks/`; no public superiority language before this gate.
- Sizing: 2–3 sessions. M0/M1/M2 parallel with Release 1; M3 blocked on it.

## Release 1 — v1.1.0 "frame engine v2" (flag-bundled; benchmark-gated)

- **R1-0. Task zero: fixture audit.** Grep the whole suite for pinned frame counts/timestamps/dedup expectations (test_dedup.py, test_frames.py, control-conformance, evidence fixtures). Emit the migration list BEFORE any frames.py edit. >15 pinned assertions → resize R1 on the spot.
- **R1-flag. One experimental engine flag** (`WATCH_FRAME_ENGINE=v2`, default v1) bundling R1a+R1b+R1c. Old engine untouched while v2 is tuned **jointly** (thresholds share units — tuning them sequentially against different comparators is invalid). Default flip is its own commit after the combined gate passes; v1 tests become a frozen legacy module deleted at flip, not maintained in parallel.
- **R1a. Comparator: RGB max-channel changed-cell %.** rgb24 16×16 thumbnails; cell "changed" when max-channel delta > tolerance; keep when changed-cell % > threshold; constants pinned in spec; JPEG-stable synthetic fixtures. Contract tests first: equal-luma red→green kept; caption-swap kept; grain-only dropped.
- **R1b. Sliding-window dedup.** Window N=4 kept thumbnails + time horizon T=90s (a return to scene A outside T is kept); both tunable; deletion/reindex/fail-open per existing contract. `test_dedupe_keeps_all_distinct` (A→B→A→B, zero drops) is explicitly rewritten to the new contract — contract test written first.
- **R1c. Density floor = post-dedup gap-fill, NOT pinned-cue inflation.** After dedup, fill any inter-frame gap > floor interval; hard budget share ≤30% of the active cap; interval auto-widens to `max(user_floor, duration/(0.3·cap))` so floor can never starve scene selection. Scope: balanced/token-burner full-video runs only — disabled under focus mode and efficient/keyframe mode. Accept: synthetic 10-min static-with-2-cuts → no post-dedup gap exceeds the effective interval; normal-video budgets unchanged.
- **R1d. `--fps` cap opt-out + path unification.** Explicit `--fps > 2` lifts the clamp; nonpositive rejected; without the flag, selected timestamps byte-identical. Known divergence to fix: `watch.py:324` clamps, standalone `frames.py:736` does not — unify both through one code path. Benchmark-gated.
- Ship: migrated tests green, version sync, tag, verify published artifact, dev-sync local installs, CHANGELOG prior-art credits (claude-real-video for R1a–R1c ideas; upstream PR #60/#37 for R1d).
- Sizing: 2–3 sessions.

## Release 2 — v1.2.0 "transcript correctness + durable evidence"

- **R2a-1. Chunk-level silence gate (pipeline-wide; zero new deps).** The v2 design (VAD inside WhisperCliAdapter) was structurally wrong: adapter order is local-http → yap → whisper-cli, so a silent clip reaches local-http FIRST and hallucinates before any VAD runs — and a zero-segment result currently reads "unavailable," causing fall-through (potentially uploading silence to cloud). Fix at the shared layer: `transcription_chunks.py` already runs `silencedetect`; classify all-silent inputs there and short-circuit to a new terminal `no_speech` state BEFORE any adapter runs. Enumerated touchpoints (each with a contract test first): `TRANSCRIPT_STATES` frozenset, fatal-requires-failure_code invariant, `usable()`, pipeline loop `transcription.py:368-378` (no fall-through on no_speech), report rendering ("no speech detected" ≠ "none available"), chunk receipts (no_speech cached so resume doesn't re-probe), evidence-mode fallback.
- **R2a-2. Silero VAD in whisper-cli only (best-effort accuracy tier).** For music/noise audio that ffmpeg calls "not silent" but contains no speech. Our pinned model download, SHA-256 from pinned constant, 0600 cache, offline → skip, fail-open to non-VAD. Gated on false-negative fixtures (quiet speech kept) and WER-neutrality.
- **R2b. Word-level timestamps.** `words[]` on `TranscriptSegment` (absent-tolerant); nested offset shifting; `segments_from_response` + every adapter; **receipt schema/key bump** so stale segment-only receipts can't mask the feature. Fail-open.
- **R2c. Silence-chunking delta.** Tight→loose threshold fallback (-35dB/0.40s → -30dB/0.2s), `hard_cut` classification, warnings to report, continuity/offset invariants. Normal audio: byte-identical boundaries.
- **R2d. Media-rich portable bundles.** Extend existing `portable.py` `export_bundle` with `include_media=True` (frames/transcript/timeline into the existing schema-versioned checksummed bundle). NOT a new schema. Accept: export→verify→replay round-trip; refs resolve; no absolute paths/secrets; new surfaces sanitized; `test_portable.py` extended.
- Sizing: 1.5–2 sessions.

## Backlog (re-entry conditions unchanged from v2)

A4 grids (quality gate + tile spec) · C2 vault ingest (CLI/config consent) · C3 audio signals · C4 Windows (needs Windows CI) · B2 model ownership · settled-local channel (decide from R1 ablation data) · cloud audio-tags · descriptions-offload · --hook/pacing · exploratory transcription bake-off track.

## Risks & tripwires

1. Fixture audit >15 pinned assertions → resize R1 before starting.
2. Joint tuning finds no config passing the combined gate → ship R1b+R1c only under the flag; defer comparator with ablation data published.
3. M0 calibration fails on a corpus video → fix before M1 freeze; never freeze a protocol our own tool can't run.
4. no_speech contract: one adapter contract test red-first per touchpoint; any surprise dependent found mid-flight → stop, extend the touchpoint list, don't patch ad hoc.
5. Schedule: 6–8 sessions realistic. Cut order if squeezed: R1d → R2b → R2d; never cut M1/M2 (they gate all public claims).
