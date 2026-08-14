# /watch — full flag reference

The common flags live in SKILL.md. These are the rest. Read this file before
using any flag not listed inline there.

## Frame selection and cost

- `--max-frames N` — override the preset cap for a tighter token budget (e.g. `--max-frames 40`)
- `--resolution W` — frame width in px (default 512; bump to 1024 only if the user needs to read on-screen text — it roughly quadruples image tokens per frame)
- `--fps F` — override auto-fps (clamped to 2 fps max)
- `--no-dedup` — keep near-duplicate frames. By default a frame-delta pass drops frames visually near-identical to the previous kept one (held slides, static screen recordings, paused video) so the frame budget goes to distinct content; the report's **Frames** line notes how many were dropped. Pass this only if the user needs every sampled frame (e.g. judging subtle frame-to-frame motion).
- `--timestamps T1,T2,…` — grab a frame at each absolute timestamp (`SS`, `MM:SS`, or `HH:MM:SS`). Use after reading the transcript to capture deictic moments the presenter flags ("look here", "as you can see", "notice this") that visual selection alone may miss. See "Transcript-cue frames" in SKILL.md.

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
