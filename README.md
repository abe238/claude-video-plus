# /watch — claude-video-plus

**Ask a video a question and `/watch` fetches only the evidence that answers it. In one initial 38-minute benchmark, evidence mode used 60–79% fewer estimated reader tokens and tied or won three blind-judged questions; broader testing is still in progress. Fork of [bradautomates/claude-video](https://github.com/bradautomates/claude-video) — same one-command install, evidence mode added, automatic compatibility fallback.**

> [!NOTE]
> This repository is a derivative of [bradautomates/claude-video](https://github.com/bradautomates/claude-video), created by Brad Bonanno and distributed under the MIT License. The full upstream Git history and license are preserved. We are grateful to Brad for designing and openly sharing the reliable foundation this work builds on — see [Gratitude](#gratitude-and-attribution).

**Website:** [abe238.github.io/claude-video-plus](https://abe238.github.io/claude-video-plus/) · **Benchmark data:** [docs/benchmarks/](docs/benchmarks/)

> [!IMPORTANT]
> **[`1.0.0`](https://github.com/abe238/claude-video-plus/releases/tag/v1.0.0) is the first stable release.** It passes 335 deterministic local tests, the hosted macOS/Linux Python 3.11–3.14 matrix, an isolated `npx skills` lifecycle, and bundle verification. Performance claims remain deliberately narrow: the published 60–79% savings come from one video and three questions, with raw evidence available for inspection. See the [status page](docs/V1-STATUS.md) and [benchmark data](docs/benchmarks/).

## Install

Claude Code (recommended — auto-updates via marketplace):
```
/plugin marketplace add abe238/claude-video-plus
/plugin install watch@claude-video-plus
```

Codex, Cursor, Copilot, Gemini CLI, or any of 50+ [Agent Skills](https://agentskills.io) hosts:
```bash
npx skills add abe238/claude-video-plus -g
```
(`-g` installs globally for your user. Drop it to scope per-project.)

Zero config to start — `yt-dlp` and `ffmpeg` install on first run via `brew` on macOS (Linux/Windows print exact commands). Captions cover most public videos for free. A Whisper API key is only needed when a video has no captions.

## Why this over claude-video

The original `/watch` samples the whole timeline — 50–100 frames plus the full transcript — no matter what you asked. That's ~50k tokens per question on a 40-minute video, most of it irrelevant to your question.

This fork adds **evidence mode**: pass your question and the pipeline retrieves only what answers it — whole topical chapters (YouTube chapters when present, pause-gap segmentation otherwise), a **numeric guard** that rescues pricing/benchmark/spec lines buried anywhere in the video (with a frame at each, because numbers are usually on-screen), frames at chapter starts and "as you can see" cue moments, and a token-budget governor. Every selection is recorded in an evidence manifest with its timestamp, reason, and score — so you can audit exactly why the model saw what it saw.

```
/watch <url> --detail evidence --question "what's actually new — skip the hype?"
```

**Measured, blind-judged, same video, same questions** (38-min launch video, 3-judge blind panels with position swap, paired against the original's `balanced` mode; [raw data + methodology](docs/benchmarks/)):

| Question class | Original tokens | Evidence tokens | Reduction | Blind quality (orig vs this) |
|---|---|---|---|---|
| Coverage summary | 50,941 | 20,148 | **−60%** | 8.33 vs **9.33** — win |
| Targeted (cost/specs) | 50,941 | 11,505 | **−77%** | 9.00 vs 9.00 — tie |
| Targeted (feature) | 50,941 | 10,555 | **−79%** | 8.33 vs **9.33** — win |

Two reader-level rules the benchmark loop proved out are now part of the skill contract: **mine on-screen tables from frames** (pricing pages, leaderboards — content nobody reads aloud) and **reconcile conflicting claims** (presenters misspeak; the judges credited this fork for catching a real pricing self-contradiction the original repeated).

Everything else — the four original detail modes, focused `--start`/`--end` ranges, `--timestamps` cues, Whisper fallback, and frame dedup — remains available. No question means no evidence mode. Behavioral conformance against the frozen upstream Control is a v1 release gate; this repository does not claim byte-for-byte identity.

## Tradeoffs — read before adopting

Direct answers, because you don't have time to discover these yourself:

- **Evidence mode needs a question.** Without `--question`, the standard non-evidence path runs. Evidence mode is opt-in per invocation; behavioral conformance with the frozen upstream Control remains a v1.0 release gate.
- **It can take slightly longer end-to-end.** Evidence compilation adds ~1.5–2s after download, and the reader is instructed to mine frames more carefully. You're trading a little wall time for a lot of tokens and (measured) better answers.
- **URL sources with captions only, today.** Local files and caption-less videos automatically fall back to the original `balanced` mode — you lose nothing, but you also gain nothing there yet.
- **Coverage/summary questions keep the full transcript by design** (top-k retrieval on a summary question is how you miss stories). Savings there come from smarter frames and transcript dedup (−60%), not retrieval; the big cuts (−77/79%) are on targeted questions.
- **Local transcription stays optional.** Same-name `.vtt`/`.srt`, loopback OpenAI-compatible `:8082`, and detected YAP run before cloud; nothing is installed automatically.
- **Cloud transmission is explicit.** Groq/OpenAI audio and remote semantic scoring require separate authorization flags/configuration.
- **OpenCV is not included.** Its measured prototype lost to the FFmpeg/stdlib approach on the available recall, duplicate, and scoring-time comparison.
- **Retrieval is lexical (tf-idf + guards), not semantic.** A question with zero word overlap with the video's language can under-retrieve. The numeric guard, facet expansion, and chapter roll-up exist to blunt this; the fallback catches the rest.
- **The benchmark is honest but small.** It is one deep-dive with LLM judges and blind paired panels; the multi-video battery is still in progress. These are measurements with raw data you can audit, not a preregistered statistical trial. The confirmatory protocol is specified in the [v1 master plan](docs/plans/V1.0-MASTER-PLAN.md) and [measurement contract](docs/execution/v1/MEASUREMENT.md) and runs before any stronger claim.
- **Full video still downloads for frame extraction** (same as upstream's frame modes). Range downloads are planned, not shipped.

## Usage

```
/watch https://youtu.be/dQw4w9WgXcQ what happens at the 30 second mark?
/watch https://www.tiktok.com/@user/video/123 summarize this
/watch ~/Movies/screen-recording.mp4 when does the UI break?
```

Evidence mode (question-aware retrieval):
```
/watch "$URL" --detail evidence --question "what's actually new — skip the hype?"
/watch "$URL" --detail evidence --question "what did they say about pricing?"
```

Focused on a specific section — denser frames, lower token cost:
```
/watch https://youtu.be/abc --start 2:15 --end 2:45
/watch "$URL" --start 1:12:00            # from 1h12m to end
```

Other knobs (passed to `scripts/watch.py`):

- `--detail transcript|efficient|balanced|token-burner|evidence` — fidelity/speed dial. `transcript` skips frames; `efficient` uses fast keyframes (cap 50); `balanced` uses scene-aware frames (cap 100); `token-burner` is uncapped; `evidence` retrieves per-question (requires `--question`).
- `--question "…"` — your question, verbatim; drives evidence-mode selection.
- `--timestamps T1,T2,…` — grab a frame at each absolute timestamp.
- `--max-frames N` / `--resolution W` / `--fps F` — budget and fidelity overrides.
- `--whisper groq|openai` / `--no-whisper` — transcription backend control.
- `--no-dedup` — keep near-duplicate frames.
- `--out-dir DIR` — keep working files somewhere specific.

## How it works

1. **You paste a video and a question.** URL (anything yt-dlp supports) or a local path.
2. **`yt-dlp` checks captions first.** At `transcript` detail, captioned URLs return without downloading video.
3. **Frame extraction at the chosen detail.** Original modes sample the timeline; `evidence` mode selects per-question (chapters → spans → tf-idf + facet expansion → numeric guard → sufficiency check → chapter/cue/guard frames).
4. **Transcript from captions, Whisper as fallback** (Groq preferred, OpenAI supported).
5. **Frames + transcript (or evidence manifest) are handed to Claude**, which Reads every frame as an image — with instructions to mine on-screen tables and reconcile conflicting claims.
6. **Claude answers grounded in what's on screen and in the audio**, citing timestamps.

### Control-lineage detail modes — initial measurement

Numbers from a real run against a 49:08 YouTube video (1280×720, English auto-captions):

| Mode | Engine | Frames | Extraction time | Est. image tokens |
|------|--------|--------|-----------------|-------------------|
| `transcript` | none (captions) | 0 | ~4.5 s (no download) | 0 (≈26.6k text) |
| `efficient` | keyframe | 50 | ~0.5 s | ~9.8k |
| `balanced` | scene-change | 100 | ~20.9 s | ~19.7k |
| `token-burner` | scene-change | 116 (uncapped) | ~21.0 s | ~22.8k |

Frame budgets, dedup behavior, and focused-mode details are documented in [skills/watch/SKILL.md](skills/watch/SKILL.md).

## More install options

| Surface | Install |
|---------|---------|
| **Claude Code** | `/plugin marketplace add abe238/claude-video-plus` then `/plugin install watch@claude-video-plus` |
| **Codex, Cursor, Copilot, Gemini CLI, +50 more** | `npx skills add abe238/claude-video-plus -g` |
| **claude.ai** (web) | Download [`watch.skill`](https://github.com/abe238/claude-video-plus/releases/download/v1.0.0/watch.skill) → Settings → Capabilities → Skills → `+` |
| **Manual / dev** | `git clone https://github.com/abe238/claude-video-plus.git && ln -s "$(pwd)/claude-video-plus/skills/watch" ~/.claude/skills/watch` |

Update later with `/plugin update watch@claude-video-plus` or `npx skills update watch -g`.

The public repository supports the same one-command install flow as the original skill.

## Structure

```
.
├── skills/watch/                 # self-contained skill — this is the whole install package
│   ├── SKILL.md                  # skill contract — source of truth across all hosts
│   └── scripts/                  # watch.py, evidence.py, download/frames/transcribe/whisper/setup/config
├── docs/benchmarks/              # supplemental evidence data (NOT in the install package)
├── docs/plans/                   # canonical v1 master plan plus historical review records
├── tests/                        # deterministic pytest suite
└── .claude-plugin/ .codex-plugin/ .agents/   # host manifests
```

## Develop

```bash
python3 -m pytest -q                          # full deterministic suite
bash skills/watch/scripts/build-skill.sh      # → dist/watch.skill (requires clean tree)
./dev-sync.sh                                 # mirror working tree into installed plugin cache
```

## Gratitude and attribution

This fork exists because **Brad Bonanno** ([@bradautomates](https://github.com/bradautomates)) built and openly shared [claude-video](https://github.com/bradautomates/claude-video) — a genuinely reliable foundation whose design decisions (caption-first, self-contained skill folder, fail-open everything) this fork inherits wholesale. The upstream Git history, MIT license, and original authorship are intentionally preserved. Brad makes content about building with AI on [YouTube](https://www.youtube.com/@bradbonanno), check them out.

We also appreciate the maintainers whose tools make the runtime possible:

- [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) and [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) — the entire media layer
- Whisper transcription via [Groq](https://groq.com) or [OpenAI](https://openai.com)

The evidence-mode design draws on published research — VideoTree, Adaptive Keyframe Sampling, PixelRAG, and others — credited with transferability cautions in the [v1 master plan](docs/plans/V1.0-MASTER-PLAN.md). The bounded execution and independent-review process is inspired by Miguel Rios's [`miguelrios/unc-skills`](https://github.com/miguelrios/unc-skills), especially Cascade and Parable.

We are also grateful to the fork authors whose public work helped us identify mechanisms worth evaluating for v1.0. Credit here records design influence and evaluation provenance; it does **not** claim their source code or every listed feature currently ships. If a mechanism is promoted, its exact origin, revision, license, modifications, and release-note credit must be recorded first.

- [`taeloautomates/claude-video`](https://github.com/taeloautomates/claude-video) — YouTube SABR/client and cookie-resilience concept.
- [`thedirektor/claude-video`](https://github.com/thedirektor/claude-video) — classified acquisition retries, focused transcription, resume/cache, OCR, and testing ideas.
- [`RadoslavSheytanov/claude-video`](https://github.com/RadoslavSheytanov/claude-video) — caption-coverage and Whisper-reliability ideas.
- [`Tigertycoon/claude-video`](https://github.com/Tigertycoon/claude-video) and [`manojbadam/claude-video`](https://github.com/manojbadam/claude-video) — sidecar-first transcript ideas.
- [`CJNA/claude-video`](https://github.com/CJNA/claude-video) — Fathom source exploration, deferred from v1.0.
- [`sciencemj/claude-video-local`](https://github.com/sciencemj/claude-video-local) — local transcription and portable-bundle architecture.
- [`troyshelton/claude-video`](https://github.com/troyshelton/claude-video), [`jsstn/claude-video`](https://github.com/jsstn/claude-video), and [`danielfrey63/claude-video`](https://github.com/danielfrey63/claude-video) — local and pluggable transcription patterns.
- [`joweiser/claude-video`](https://github.com/joweiser/claude-video) and [`JoseBallestas/claude-video`](https://github.com/JoseBallestas/claude-video) — silence-aware chunks, focused transcription, bounded retries, and diagnostics.
- [`finnvoor/yap`](https://github.com/finnvoor/yap) and the faster-whisper server ecosystem — optional local transcription references; neither is automatically installed.
- [`DanielZYoffe/claude-video-lite`](https://github.com/DanielZYoffe/claude-video-lite) — PySceneDetect reference evaluated in the documented OpenCV ablation; that Adapter was rejected for v1.0.

The canonical mechanism-by-mechanism disposition is maintained in [PROVENANCE.md](docs/execution/v1/PROVENANCE.md).

## License

MIT — see [LICENSE](LICENSE). Original work © Brad Bonanno; derivative changes © Abe Diaz.
