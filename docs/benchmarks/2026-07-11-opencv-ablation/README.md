# OpenCV development ablation

Decision: **do not add OpenCV to v1.0**.

This development test asked whether a more sophisticated OpenCV frame-change scorer
earned its installation and runtime cost. It did not. This is a product decision from a
small development benchmark, not a claim that OpenCV can never help another project.

## Results

| Test | Current 16×16 scorer | OpenCV composite |
| --- | ---: | ---: |
| Real-video curated-moment recall | 6/12 | 5/12 |
| Real-video scoring time | 63.5 ms | 304.1 ms |
| Real-video selected frames | 100 | 100 |
| Estimated reader-image tokens | 19,700 | 19,700 |
| Real-video near-duplicate pairs | 0 | 1 |
| Synthetic event recall, 10-frame budget | 5/6 | 5/6 |
| Synthetic median scoring time | 4.0 ms | 18.0 ms |

The local environment had OpenCV 4.13.0 and NumPy 2.4.4 on Python 3.14.4, macOS
arm64. The installed `cv2` directory occupied about 119 MB and NumPy about 24 MB. A
downloaded headless OpenCV wheel was about 44 MB. Cold `import cv2` took roughly
0.08–0.09 seconds and raised process memory from about 15.5 MB for baseline Python to
about 56.8 MB.

## Method

Both prototypes scored the same dense half-frame-per-second samples and selected the
same 100-frame budget. The current scorer used 16×16 grayscale mean differences. The
OpenCV composite combined larger grayscale local change, edge change, and HSV histogram
distance. A separate 14-second synthetic clip contained six known events: a small UI
toggle, small price/text change, hard cut, gradual transition, motion, and motion stop.

For context, the shipped FFmpeg scene pipeline selected 100 frames from the real video
in about 5.26 seconds and landed within four seconds of 2/12 curated moments. That number
is not directly comparable to the dense score-only prototypes because the shipped path
uses a different candidate-generation and extraction pipeline.

## Limitations

- This used one real video and one synthetic fixture.
- The 12 real-video moments came from a previously curated evidence manifest, not a new
  independent gold-labeling pass.
- Recall within four seconds and perceptual duplicates are proxy metrics, not answer
  quality.
- The composite was a development prototype, not an exhaustively tuned OpenCV system.
- One edge-only OpenCV signal reached 8/12 proxy recall, but remained slower, was not
  shown to reduce tokens or improve answers, and does not justify the dependency.

These limitations prevent a broad scientific conclusion. They do not reverse the v1.0
product decision: the tested dependency added cost without a demonstrated total-system
benefit. Future vision improvements must use FFmpeg plus standard-library Python unless
materially new evidence and explicit owner approval reopen ADR-0001.

Machine-readable summary: [results.json](results.json).
