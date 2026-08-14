# OCR ablation — 2026-08-14 (NEGATIVE: do not promote)

Resolves the `evaluate-only` OCR row in `docs/execution/v1/PROVENANCE.md`, which
required "no runtime promotion without separate gate and owner approval" and
"publish negative/positive ablation and sources". **Result: negative.** OCR is
not promoted.

## What prompted it

[`Stefan-codestar/claude-video`](https://github.com/Stefan-codestar/claude-video)
shipped a Tesseract OCR pass and argued a token asymmetry in its `FORK.md`:

> frames cost *image* tokens, OCR output costs *text* tokens — roughly two orders
> of magnitude less. So the cheap move is to OCR generously at a resolution where
> small text is actually legible, and spend image tokens only on the handful of
> frames where layout or imagery matters.

This is the strongest OCR argument any fork has made, so it got a real test
rather than a restatement of the prior rejection.

## Method

- **Video**: `ZDa-Z5JzLYM` — Corey Schafer, "Python OOP 1: Classes and Instances"
  (15 min). Chosen because it is **V2 of the frozen corpus-9 benchmark set**
  (`docs/benchmarks/2026-07-bakeoff/corpus9/QUESTIONS-FROZEN.md`, tagged
  `[screencast]`) and is the best case for OCR: dense small monospace code, the
  exact content where a 512px viewing frame is supposed to fail.
- Acquired through our own pipeline (`watch.py --detail balanced`); raw `yt-dlp`
  hit HTTP 403 and our acquisition ladder recovered it.
- 6 timestamps (120/240/360/480/600/720s), each extracted twice: **512px** (our
  shipped default) and **1600px** (`OCR_RESOLUTION`, the fork's default).
- Tesseract 5.5.3 (Homebrew) on both.
- Token accounting per `docs/benchmarks/README.md`: text = chars/3.6,
  image = w×h/750.
- **Ground truth: the vision model read the 512px frames directly** — the honest
  comparison, since the alternative to OCR is not "nothing", it is the model
  reading the frame we already send.

## Cost result

| quantity | tokens/frame |
|---|---|
| OCR text from a 1600px frame | **105** |
| our shipped 512px frame | **196** |
| a 1600px frame (never sent by us) | **1920** |

OCR pass wall cost: 0.6s for 6 frames (~0.1s/frame). Cost is not the blocker.

**The fork's ~20x claim compares OCR text against a 1600px frame (0.05x). We
never send 1600px frames.** Against the frame we actually send, OCR text is
0.54x — a 46% saving, not 95%.

## Accuracy result (the decisive one)

A saving only exists if OCR text *replaces* the frame. It cannot, because it is
less accurate than the model reading the cheap frame.

At **t=360**, Tesseract on the **1600px** frame produced:

```
def lime (Gain first, last, pay):
...
emn 2 email = 'Tect Icer@camnany com!
```

The model reading the **512px** frame read the same lines correctly:

```
def __init__(self, first, last, pay):
...
emp_2.email = 'Test.User@company.com'
```

At **t=480**, Tesseract on 1600px emitted `emp_l.last`, `emp_l.email`,
`emp_l.pay` — digit `1` misread as letter `l` throughout — and dropped the `=`
from `emp_2 = Employee(...)`. The model read all of them correctly at 512px.

For code, these are the **worst** possible errors: silent, syntactically
plausible, and invisible without the frame you were trying to avoid sending.

OCR on our existing **512px** frames is not an option either — it is pure noise
(14–143 chars/frame of the form `Get tose oat, fate tasty po`, `eet = etoyeed`).

## Verdict

**Negative — do not promote.** The asymmetry arithmetic is right; it answers the
wrong question. As a *replacement* for frames OCR loses accuracy on the content
type it should win. As a *supplement* it is +105 tokens/frame (+54%) for text the
model already reads correctly for free.

One variant was raised and **declined by the owner on 2026-08-14**: OCR as a
cheap *pre-scan* to choose which frames earn image tokens (rather than as
evidence itself), where Tesseract's errors might be tolerable because the output
is only a ranking signal. It would have to beat evidence mode's existing
query-aware selection (transcript + chapters + numeric guards) rather than fill
a gap. **The OCR question is closed in every form — do not reopen it.**

## Reproduce

```bash
brew install tesseract
python3 skills/watch/scripts/watch.py "https://www.youtube.com/watch?v=ZDa-Z5JzLYM" \
  --detail balanced --no-whisper --out-dir /tmp/ocrtest/run --max-frames 40
for t in 120 240 360 480 600 720; do
  ffmpeg -loglevel error -y -ss $t -i /tmp/ocrtest/run/download/video.mp4 -frames:v 1 \
    -vf "scale=1600:-2:flags=lanczos" -q:v 2 "/tmp/ocrtest/o$t.jpg"
  tesseract "/tmp/ocrtest/o$t.jpg" "/tmp/ocrtest/o$t"
done
```

Then read the 512px frames with the Read tool and diff against `o*.txt`.
