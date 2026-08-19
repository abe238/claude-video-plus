# /watch — transcription backends and configuration

Read this when choosing or configuring a transcription backend, setting a
language, or explaining where audio goes. The binding privacy rule is in
SKILL.md: cloud audio is never sent without `--allow-remote-transcription`.

## Backend order

The normalized transcript pipeline stops at the first usable source:

1. native captions;
2. same-basename `.vtt` or `.srt` sidecar;
3. configured loopback OpenAI-compatible server (default `127.0.0.1:8082`);
4. detected YAP on macOS;
5. detected `openai-whisper` CLI, any platform (`pip install openai-whisper`) — a real speech model on this machine, no server and no network. Often the only local option on Linux;
6. explicitly authorized Groq, then OpenAI;
7. frames-only fail-open result.

Every local option is exhausted before anything leaves the machine. Set `WATCH_STT_ORDER`, `WATCH_STT_URL`, `WATCH_STT_MODEL`, `WATCH_WHISPER_CLI_PATH`, `WATCH_WHISPER_CLI_MODEL`, and `WATCH_LANGUAGE` in
`~/.config/watch/.env`. `WATCH_LANGUAGE` controls caption-track selection too: an ordered list like `es,en` fetches and prefers those subtitle tracks (manual tracks beat auto-generated within each language). It is normalized per adapter (yap needs `en_US`, the whisper CLI needs `en`), so set it once in whichever form you like. YAP, local servers, and the whisper CLI are detected, never installed. Cloud audio is never
sent without `--allow-remote-transcription` (or explicit `WATCH_STT_ALLOW_REMOTE=true`). Focused
requests extract only the requested range before inference, restore absolute timestamps, split
near silence, and reuse successful owner-only chunk receipts after interruption.

## Remote cost bound

Authorized cloud transcription is budgeted per run: `WATCH_REMOTE_MAX_UPLOAD_MB`
(default 256) caps cumulative uploaded bytes and `WATCH_REMOTE_MAX_ATTEMPTS`
(default 171) caps HTTP send attempts — retries and the Groq→OpenAI fallback
draw from the same pool. Set either to `0` to disable that bound. When a bound
trips, completed chunks are kept, no further remote upload happens, local
adapters may still run, and the run degrades to a partial or frames-only
SUCCESS whose report suggests re-running with `--start/--end` for a focused
section.

Evidence mode adds dependency-free lexical retrieval, exact-number/negation/before-after guards,
bounded sufficiency expansion, conflict reporting, and verified Scout reuse. Semantic reranking is
optional and fail-open. Vision remains FFmpeg plus standard-library Python: the measured OpenCV
prototype lost on recall, duplication, and scoring time, so no OpenCV dependency or Adapter ships.

