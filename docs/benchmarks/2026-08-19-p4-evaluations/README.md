# P4 evaluations: section download & WAV-vs-MP3 (2026-08-19)

Evaluate-only, per docs/plans/2026-08-18-fork-deep-pass.md P4: numbers before
any port. Ideas from `m1crodevil/hermes-video` (section downloads) and
`EmilyYoung71415/claude-video` (WAV for local whisper).

## (a) Section download vs full download — focused first runs

Setup: Blender "Spring" (WhWc3b3KhnY, 464 s), yt-dlp 2026.7.4, macOS,
`player_client=mweb` + node JS runtime, format `b[height<=720]/b`, 30 s
section (04:00–04:30). Single measurements on residential broadband.

| leg | bytes | wall | duration |
|---|---|---|---|
| full download | 15,241,259 | 2.9 s | 464.1 s |
| `--download-sections *04:00-04:30` | 1,308,016 | 2.1 s | 30.1 s |

- **Bytes: section = 8.6 % of full (11.6x less transfer).** Real and large.
- **Wall: 2.1 s vs 2.9 s on the measured connection** (single run, one
  video). Hypothesis, unmeasured: byte savings would matter more on
  slow/metered links.
- **Client fragility (measured, same video, same day):** section downloads
  FAILED on `android_vr` (our primary client — data-plane 403), `tv` ("page
  needs to be reloaded"), `web`/`ios` (format unavailable), default (ffmpeg
  exit 8). Only `mweb` worked. Our acquisition ladder is built around
  android_vr because tv/mweb gate formats behind PO tokens for many videos —
  a section feature would inherit a materially worse client matrix.
- Section files are 0-based: every frame timestamp, transcript offset, and
  evidence citation would need rebasing (the absolute-timestamp invariants
  the pipeline just spent releases hardening).

**Verdict: DO NOT PORT now.** The byte savings are real but wall-time gains
were small on the measured connection; the client matrix for sections is measurably
worse than for full downloads; and the timestamp-rebasing surface is large.
(v1.5.5's opt-in cache removes REPEAT-download cost only — section downloads
target cold first runs, which no cache can help — so the fragile client
matrix and the rebasing surface are the load-bearing reasons.) Revisit only
if slow-link users report pain, and then behind the same fail-open ladder.

## (b) WAV vs 64 kbps MP3 for local whisper (whisper-cli, ggml-small.en)

Setup: 195 s / 587-word exact-ground-truth speech fixture (macOS `say`,
scripted text), encoded per the production shape (`-ar 16000 -ac 1`): WAV
pcm_s16le 6,242,222 B vs MP3 64k 1,561,581 B. whisper.cpp `whisper-cli`,
3 runs each (outputs deterministic across runs). WER is standard Levenshtein
(S+D+I)/reference after case/punctuation folding — `wer.py` in this
directory recomputes it from the archived `reference.txt` and
`transcript-{wav,mp3}.txt` (reproduction commands in its docstring).
Environment: fully labeled in `model-checksum.txt` (macOS product/build
version, Darwin release, whisper-cpp version, model file + SHA-256, TTS
voice settings).

| encoding | WER (Levenshtein) | hypothesis word count | wall (median of 3) |
|---|---|---|---|
| WAV 16 kHz | **11.41 %** | 541/587 | 3.1 s |
| MP3 64 kbps | **16.87 %** | 502/587 | 3.1 s |

- **The 64 kbps MP3 costs 5.5 WER points on this fixture** at identical
  latency. On a short, clean real-speech control (jNQXAC9IVRw, 19 s) both
  encodings produced byte-identical transcripts. That the penalty grows
  with length/density is a HYPOTHESIS from these two fixtures, not a
  measured curve.
- Caveats: TTS voice (single speaker, clean channel), one fixture, small.en
  model. Absolute WERs are inflated by TTS prosody; the DELTA is the signal.

**Verdict: PROMISING — port as a follow-up candidate, not blind.** The port
is not a one-liner: audio preparation is shared by every adapter, so WAV for
local means per-adapter format selection (remote uploads must stay MP3 — WAV
is 4x the bytes against the remote cost ledger and the 25 MB per-chunk cap)
plus receipt-key awareness. Follow-up should re-measure on 2-3 real-speech
videos with human captions before committing.
