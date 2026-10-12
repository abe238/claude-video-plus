# --boundary-anchors receipt (2026-10-11)

Opt-in flag, default path unchanged. Not a selection-quality benchmark against
control `83da59f`; it is a mechanism demo plus a cost measurement. Machine: this Mac, ffmpeg with software AV1 decode.

## 1. Synthetic miss (180 s lavfi clip)

testsrc2 content with a 4 s slow fade-out to a 0.6 s black gap (about 100.3 s) and a
1.4 s solid-blue card at 142.2 to 143.6 s. `--detail balanced`, uniform sampling,
80-frame budget, i.e. a frame every 2.25 s (141.75 s, then 144.0 s).

- Default: no frame inside the card (nearest frames 141.75 s and 144.0 s). The card is never seen.
- `--boundary-anchors`: boundary pass returned `[100.43, 101.45, 142.37]`; 3 anchors added
  (shared cap 97 vs 100 detail frames). The cue frame at about 142.4 s is pure blue (mean RGB 0,0,255), i.e. the card.
- Caveat: the black gap sits on a 2.25 s grid that hits the fade-up region anyway
  (frames at 99.0 / 101.25 s), so only the held card is a clean miss in this clip.

## 2. Cost on a real video

Big Buck Bunny, 10:35 (634.6 s), AV1 1280x720, fetched with our own skill
(`watch.py <url> --out-dir ... --detail balanced`; the first URL run took 6m01s including the download).
Local-file runs, `--detail balanced`:

| run | wall clock |
|---|---|
| default #1 / #2 | 356.9 s / 351.7 s |
| `--boundary-anchors` #1 / #2 | 365.7 s / 372.1 s |
| boundaries pass alone (3 runs) | 11.7 s / 12.0 s / 12.7 s |

Overhead is about 12 s, roughly 3 to 5 percent of the default run (the scene pass dominates).

Cost to frame quality: the pass found 79 boundaries in this animated film; 30 were
anchored (the 30% share of the 100-frame cap), so the detail engine got 70 frames instead of 100.
Anchors are evenly down-sampled when over budget. On content full of cuts and quiet passages
that is a real trade, which is why the flag is opt-in. No claim of better answers is made here.
