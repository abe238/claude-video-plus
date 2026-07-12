# Speed and reliability — 2026-07-12

Closes the last open slice of release-handoff item 4 (speed/reliability beyond the release
validator). Measured at v1.0.2 on macOS arm64, Python 3.14, sequential runs only (parallel
runs distort wall-clock numbers). Raw data: [timings.csv](timings.csv).

## Cold end-to-end wall time (URL → finished report, includes download)

| Mode | Kurzgesagt 13:56 | Veritasium 32:44 |
|---|---|---|
| `transcript` (no frames) | 10.5 s | 11.2 s |
| `efficient` (50 keyframes) | 18.8 s | 19.3 s |
| **`evidence` (question-aware)** | **18.2 s** | **18.8 s** |
| `balanced` (default, 100 scene frames) | 33.7 s | 32.1 s |

The surprise worth stating plainly: **evidence mode is faster cold than the `balanced`
default it replaces** — about 14 s faster on both videos — because extracting ~10–30
selected frames costs far less than 100 scene-detected frames, which more than offsets the
~2 s evidence compile. It is on par with `efficient` and slower only than `transcript`
(which extracts nothing). Earlier docs said evidence mode "takes slightly longer"; that was
written before this measurement and is corrected as of v1.0.2.

## Preflight

`setup.py --check` over 20 sequential runs: **median 29 ms, p95 31 ms** — comfortably
inside the inherited sub-100 ms contract.

## Reliability (whole-project run record)

| Surface | Runs | Completed | Notes |
|---|---|---|---|
| watch.py pipeline invocations (all benchmarks) | 33 | 33 | deep-dive, battery preps, confirmatory preps, this packet — all exit 0 |
| evidence.py compiles | 38 | 38 | includes chapterless videos (pause-gap fallback exercised) |
| Sealed confirmatory evaluation | 5 videos / 40 agents | 5 / 40 | zero errors |
| Development battery (first pass) | 5 videos | 4 | one agent returned malformed output (instrument, not skill); video completed on resume; a later re-judge pass was cut short by a harness session limit — documented in that packet |
| Fallback behaviors verified live | 3 | 3 | no `--question` → original modes; <9-min video → original (v1.0.2); caption-less → covered in unit suite |

The only failures observed all project were harness-side (agent session limits, one
malformed structured output) — none were `/watch` runtime failures.

## Honest limits

One machine, one network, one run per cell (timings are indicative, not distributions);
download time depends on connection and video bitrate; reliability counts come from this
project's own receipts rather than long-term field data.
