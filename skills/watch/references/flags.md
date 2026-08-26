# /watch — full flag reference

The common flags live in SKILL.md. These are the rest. Read this file before
using any flag not listed inline there.

## Frame selection and cost

- `--max-frames N` — override the preset cap for a tighter token budget (e.g. `--max-frames 40`)
- `--resolution W` — frame width in px (default 512; bump to 1024 only if the user needs to read on-screen text — it roughly quadruples image tokens per frame)
- `--fps F` — override auto-fps (clamped to 2 fps max)
- `--no-dedup` — keep near-duplicate frames. By default a frame-delta pass drops frames visually near-identical to the previous kept one (held slides, static screen recordings, paused video) so the frame budget goes to distinct content; the report's **Frames** line notes how many were dropped. Pass this only if the user needs every sampled frame (e.g. judging subtle frame-to-frame motion).
- `--timestamps T1,T2,…` — grab a frame at each absolute timestamp (`SS`, `MM:SS`, or `HH:MM:SS`). Use after reading the transcript to capture deictic moments the presenter flags ("look here", "as you can see", "notice this") that visual selection alone may miss. Full workflow below.
- `--text-anchors` — automatically pin a frame at each transcript-segment start. Use for caption-driven or slide/screen-recording content where the meaning changes faster than the pixels: a new caption card, a single new bullet, or thin UI text can change too little for the dedup pass to keep a frame, so those states are lost. Anchoring at segment starts recovers them. Full behavior below.

## Transcript-segment anchors (`--text-anchors`)

Complements `--timestamps` (which you place by hand) by deriving anchors *automatically* from the caption track — one frame at each transcript-segment start. Segments are the post-normalization units (rolling-duplicate caption cues are already collapsed), so each start is a distinct on-screen moment. It targets the measured dedup blind spot (caption swaps, screen-recording state changes) where a change is too small to survive the frame-delta pass.

Behavior:
- **Needs captions available before frame extraction** — a URL caption track, parsed up front. On a source with no early caption track (e.g. a raw local screen recording with no sidecar), the flag **fails open**: it prints a note and runs normal extraction. It is **not applied** in `--detail evidence` (question-aware selection owns frame choice there), and stays off even if evidence mode falls back to balanced.
- **Bounded by design.** Anchors are thinned to **at most one per second**, then capped to the **exact 30% floor of the frame budget** (`floor(0.30 × cap)`, so a cap of 1–3 yields none) — or **100** when uncapped — and evenly down-sampled if over. Explicit `--timestamps` keep **precedence**: anchors may consume only the budget left after your manual cues, and can never evict one. Derivation is single-pass and bounded in memory, so even a pathological or hostile caption track can force neither unbounded frame grabs nor an unbounded anchor list. Only the numeric segment time is read; caption text is data, never a command.
- **Pinned like `--timestamps`.** Anchor frames (`reason=transcript-cue`) are reserved against the cap before the detail engine runs and merged chronologically; they honor `--start/--end` (out-of-window anchors dropped). Combine with `--timestamps` to add hand-picked moments on top.

## Transcript-cue frames (`--timestamps`)

**You** decide which moments matter, by reading the transcript:

1. Run once at `--detail transcript` (or any detail) to get the timestamped transcript.
2. Scan it for deictic cues — phrases where the speaker directs attention to something on screen. This is a judgment call (ignore rhetorical "look, the point is…"); that's why it's done by you, not a regex.
3. Re-run with `--timestamps 4:32,7:10,9:55` (absolute source times). For a URL, point the second run at the **downloaded local file** in the work dir so it doesn't re-download.

Behavior:
- **Additive by default.** Cue frames (`reason=transcript-cue`) are merged into whatever `--detail` already selected, in chronological order.
- **Pinned and counted first.** Cue frames are reserved against the frame cap before the detail engine runs, so they're never evicted by even-sampling.
- **Honors focus mode.** With `--start/--end`, any cue timestamp outside the window is dropped (reported in the summary). Coordinates are always absolute source time.
- **Cue-only frames.** `--detail transcript --timestamps …` skips scene/keyframe sampling and returns *only* the cue frames (it will download the video to do so, since frames need pixels).

## Detail-mode selection mechanics

- At `transcript` detail, captions are enough to return a report without downloading video. If captions are missing, the script downloads audio only and tries the transcription fallback. If no transcript can be produced, it reports the limitation clearly; re-run with `--detail balanced` for frames.
- At `efficient` detail, the script extracts **keyframes only** (`ffmpeg -skip_frame nokey`) — a near-instant pass that lands frames on scene cuts. If a clip has fewer than 4 keyframes it falls back to uniform sampling.
- At `balanced` / `token-burner` detail, the script extracts **scene-aware** frames: ffmpeg scene-change selection first, falling back to uniform sampling only when the video is effectively static. Frame report lines include both timestamp and selection reason.
- `token-burner` prints a soft warning past 250 frames.
- Extracted images are clamped to a maximum 1998px height for Claude Read compatibility.

## Transcription

- `--whisper groq|openai` — force a specific Whisper backend (default: prefer Groq if both keys exist)
- `--stt auto|sidecar|local-http|yap|groq|openai` — select the normalized transcription Adapter. `auto` tries local options before cloud.
- `--allow-remote-transcription` — explicitly authorize sending audio to Groq/OpenAI. Without this, cloud Adapters remain unavailable. (The policy that cloud transcription requires explicit authorization is stated in SKILL.md; this is the mechanism.)
- `--no-whisper` — disable the Whisper fallback entirely (frames-only if no captions)

## Working files and I/O

- `--out-dir DIR` — keep working files somewhere specific (default: an auto-generated tmp dir)
- `--request-json FILE` — transport a multiline or punctuation-heavy question and evidence budget without shell ambiguity
- `--diagnostics-json` — print secret-free Adapter/config diagnostics and exit

## Evidence bundles and semantic rerank

- `--export-bundle FILE` / `--verify-bundle FILE` / `--replay-bundle FILE --out-dir DIR` — portable checksummed evidence without source media by default
- `--bundle-media` — include frame JPEGs and the transcript in `--export-bundle`
- `--semantic off|local|remote` — uncertainty-triggered semantic reranking. Remote also requires `--semantic-endpoint https://… --allow-remote-semantic`.

## Video cache (opt-in)

`WATCH_VIDEO_CACHE=1` enables a local content-addressed media cache
(experimental) so repeat analysis of the same URL skips the download. Scope:
allowlisted YouTube hosts only — a generic host cannot be proven public, so
it is refused. Privacy contract: OFF by default; local files are never
copied in; cookie-authenticated, signed, private, or credential-bearing
sources are never cached — no override exists, because a cached copy would
outlive the authorization that fetched it. Entries are owner-only, verified by checksum on every hit, and
bounded by `WATCH_VIDEO_CACHE_MAX_GB` (10), `WATCH_VIDEO_CACHE_MAX_ENTRY_GB`
(2), and `WATCH_VIDEO_CACHE_TTL_DAYS` (30). A cache failure of any kind
falls back to a fresh download. Inspect or clear:
`python3 "${SKILL_DIR}/scripts/video_cache.py" --inspect` to list entries;
`python3 "${SKILL_DIR}/scripts/video_cache.py" --purge` to delete the cache
(or `lifecycle.py --purge-cache` for all watch caches).
