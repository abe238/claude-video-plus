# OpenCV is rejected for v1.0

Status: accepted, superseding the earlier optional-Adapter proposal

## Decision

Do not add OpenCV, PySceneDetect, an installer choice, an environment variable, or a
runtime fallback for either library. Keep vision scoring on FFmpeg plus standard-library
Python.

## Evidence

The 2026-07-11 development ablation found no total-system win. On the real 38-minute
benchmark video, the composite OpenCV prototype recovered 5/12 previously curated screen
moments versus 6/12 for the current 16×16 scorer, produced one additional near-duplicate
pair, used the same estimated reader-image tokens, and took about 304 ms to score versus
about 64 ms. On the synthetic six-event fixture at the shared ten-frame budget, both
recovered 5/6 events.

The benchmark is too small for a general claim that OpenCV can never help, but it is
enough to reject its wheel size, startup memory, platform maintenance, and failure
surface for this product. See [the ablation report](../benchmarks/2026-07-11-opencv-ablation/).

## Consequences

- The v1.0 plan contains only dependency-free vision work.
- OpenCV-specific code and installation guidance must not ship.
- Reopening this decision requires materially new evidence and explicit owner approval.
