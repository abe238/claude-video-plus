# Query-Adaptive Video Evidence Compiler

The detailed, benchmark-first implementation and review plan lives in two documents: [plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md](plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md) is the source of truth for sequencing, gating, and module scope (it supersedes v1's decisions on those axes after an adversarial review), and [plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN.md](plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN.md) remains authoritative for everything v2 is silent on. Treat this document as the concise architecture overview and those plans as the source of truth for control comparisons, research foundations, acceptance gates, sequencing, installation, and public claims.

## Goal

Answer questions about video with less model context than `/watch` while preserving its speed and reliability. Keep the existing caption, download, transcription, and deterministic frame-sampling paths as the compatibility fallback.

The optimization target is total model input, not just frame count. The upstream skill currently loads roughly 5.4k tokens of instructions, emits the full transcript, and can expose 100 images in `balanced` mode. A better design retrieves a small, sufficient evidence set before the reader model sees it.

## Design

Use a three-stage pipeline: **Scout -> Retrieve -> Verify**.

### 1. Scout once, locally

Build a content-addressed evidence index while captions and media download:

- segment captions or Whisper output into overlapping timestamped chunks;
- detect shots and keyframes with ffmpeg;
- compute cheap motion and perceptual-change signals;
- optionally OCR low-resolution keyframes for screen recordings and slides;
- optionally embed low-resolution frames with a compact visual encoder;
- cache the manifest by video hash so follow-up questions do not repeat work.

The required baseline index is pure local text plus ffmpeg metadata. OCR and visual embeddings are accelerators, not correctness dependencies.

### 2. Retrieve per question

Classify the question into one or more evidence needs: speech, visible text, objects/scenes, motion/change, temporal order, or exhaustive summary.

Run multiple retrievers over the same temporal chunks:

- lexical/BM25 retrieval over transcript and OCR;
- visual similarity over low-resolution keyframes when available;
- motion/change ranking for actions and UI transitions;
- explicit timestamp and relative-time parsing;
- uniform coverage for summaries and broad questions.

Fuse results with reciprocal-rank fusion, then apply temporal diversity so adjacent duplicates cannot consume the budget. Retrieve chunks, not isolated frames: each winning time span carries transcript, a representative frame, and its reason for selection.

### 3. Verify coarse-to-fine

For each winning span, extract reader-ready evidence only:

- one representative frame at low resolution;
- neighboring or boundary frames for motion and state-change questions;
- a high-resolution crop instead of a high-resolution full frame when text or a small region matters;
- the matching transcript window, not the full transcript.

Start with a small budget, such as 6-12 frames and 4-8 transcript chunks. If evidence is missing, contradictory, or temporally ambiguous, expand only the affected intervals. If retrieval components fail or confidence remains low, fall back to the upstream `efficient` or `balanced` full-range sampler.

## Why this is different

This is not merely scene detection with a lower cap. It makes the evidence unit query-conditioned and multimodal, then preserves the selected representation through retrieval and reading.

- [PixelRAG](https://arxiv.org/abs/2606.28344) shows that retrieving visual units in the representation consumed by the reader can outperform parsed text, and that resolution is a useful token-cost control.
- [VideoTree](https://arxiv.org/abs/2405.19209) supports query-adaptive, coarse-to-fine temporal refinement without video-specific training.
- [LongVU](https://arxiv.org/abs/2410.17434) combines inter-frame redundancy removal with text-guided selection and spatial compression.
- [Rethinking RAG in Long Videos](https://arxiv.org/abs/2606.13141) argues for chunk-adaptive modality and granularity rather than one configuration for an entire query.
- [MARQUIS](https://arxiv.org/abs/2605.17640) supports query expansion, reranking, and structured evidence extraction for complex multi-faceted requests.

PixelRAG itself should not be a mandatory runtime dependency. Its Qwen3-VL embedding and FAISS pipeline are designed for large document collections, while this skill needs a lightweight per-video temporal index. Borrow the representation and compression ideas; do not import the infrastructure cost. The same caution applies to VideoTree and LongVU: both report results from inside video-language models this skill does not control, so they are design evidence for the hierarchy and redundancy-removal ideas, not transferable performance claims for selecting external JPEG evidence.

## Reliability contract

Every answer should be traceable to an evidence manifest containing timestamps, source modality, selection reason, and retrieval score.

- Fail open: missing OCR or embeddings must degrade to transcript plus ffmpeg sampling.
- Preserve coverage: summaries and exhaustive questions must use uniform or hierarchical coverage, never top-k retrieval alone.
- Preserve temporal meaning: action and transition questions must include neighboring frames.
- Preserve exactness: high-resolution crops must retain their source frame and coordinates.
- Preserve repeatability: cache keys include video identity, time range, sampler version, and model version.
- Preserve privacy: local files stay local unless the user explicitly enables an external transcription or embedding service.

## Evaluation gates

Compare against upstream `transcript`, `efficient`, and `balanced` modes on the same videos and questions.

Measure:

- answer correctness and timestamp grounding;
- retrieval recall of human-labeled evidence intervals;
- total text and image tokens sent to the reader;
- cold and warm latency;
- download and local CPU time;
- failure recovery when captions, OCR, embeddings, or network access are unavailable.

Use at least these suites:

1. caption-heavy lecture summaries;
2. screen-recorded bug diagnosis with small UI changes;
3. visual questions whose answers are never spoken;
4. action and before/after questions requiring adjacent frames;
5. long videos with a narrow query;
6. exhaustive summaries where retrieval-only approaches are unsafe.

Do not claim "no compromise" until the candidate meets or exceeds upstream accuracy, p95 latency, and task completion rate while reducing median reader tokens. Keep the upstream pipeline selectable until those gates pass.

## Implementation order

The sequence is owned by the milestone structure in [plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md](plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md):

1. **Milestone A** — benchmark module, shrink the skill interface, question seam, transcript retrieval.
2. **Milestone B** — acquisition/transcription/extraction efficiency, minimal evidence store.
3. **Milestone C** — scout separation, coarse-to-fine selection, adaptive resolution and crops.
4. **Milestone D** — optional adapters (OCR, embeddings, local ASR), distribution identity, final confirmatory gate.

Query-adaptive mode becomes the default only after every gate passes.
