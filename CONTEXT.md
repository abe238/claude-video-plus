# Video evidence compilation

This context describes how `claude-video-plus` turns a video and question into the smallest sufficient reader-ready evidence while preserving coverage, grounding, and reliability.

## Language

**Video source**:
A URL or local media path supplied for analysis.
_Avoid_: input video, asset

**Question**:
The user's requested analysis of a **Video source**.
_Avoid_: prompt, query

**Evidence span**:
A timestamped interval containing one or more supporting transcript, frame, motion, OCR, or metadata signals.
_Avoid_: chunk, segment

**Scout index**:
A local content-addressed collection of low-cost descriptors used to locate **Evidence spans** without spending reader tokens.
_Avoid_: vector store, frame cache

**Evidence budget**:
The maximum reader context available for selected text and images.
_Avoid_: frame cap, token limit

**Evidence compiler**:
The module that transforms a **Video source**, **Question**, and **Evidence budget** into an **Evidence manifest**.
_Avoid_: watcher, video RAG pipeline

**Evidence manifest**:
A reproducible record of selected **Evidence spans**, timestamps, modalities, paths, reasons, scores, context cost, and fallbacks.
_Avoid_: report, output JSON

**Targeted question**:
A **Question** whose answer is expected within a limited timeline range or subset of modalities.
_Avoid_: narrow query

**Coverage question**:
A **Question** requiring representative or exhaustive coverage across the requested timeline.
_Avoid_: broad query

**Control pipeline**:
The unmodified upstream behavior at commit `83da59f` used as the experimental baseline.
_Avoid_: old version, original mode

**Candidate pipeline**:
The proposed behavior compared with the **Control pipeline** under the same case and environment.
_Avoid_: new version, optimized mode

## Relationships

- An **Evidence compiler** receives exactly one **Video source**, one **Question**, and one **Evidence budget** per run.
- An **Evidence compiler** produces one **Evidence manifest** containing one or more **Evidence spans**.
- A **Scout index** may support many **Questions** about the same **Video source**.
- A **Targeted question** prioritizes relevant **Evidence spans**; a **Coverage question** preserves representative timeline coverage.
- A **Candidate pipeline** is acceptable only when its measurements satisfy the benchmark gates against the **Control pipeline**.

## Example dialogue

> **Dev:** "The **Question** asks what changed after the button click. Can the **Evidence compiler** return only the most relevant frame?"
> **Domain expert:** "No. This is a temporal **Targeted question**, so its **Evidence manifest** must preserve before-and-after **Evidence spans** within the **Evidence budget**."

## Flagged ambiguities

- "Keyframe" can mean a codec I-frame, a scene boundary, or important evidence. Use the precise term; reserve **Evidence span** for reader-relevant material.
- "Tokens" can mean instruction, transcript, or image tokens. Report each separately and total them only with a named provider measurement.
