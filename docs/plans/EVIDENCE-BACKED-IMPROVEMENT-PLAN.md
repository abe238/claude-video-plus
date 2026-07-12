# Evidence-backed improvement plan

> Historical record. Superseded by [V1.0-MASTER-PLAN.md](V1.0-MASTER-PLAN.md).
> Its OpenCV proposals were tested and rejected; do not implement them.

Status: Independently reviewed; ready for Phase 0 benchmark implementation

Control: unmodified upstream commit `83da59f`

Candidate: commits derived from the control in `abe238/claude-video-plus`

## Objective

Reduce total reader-context usage while matching or improving the control pipeline's answer quality, evidence grounding, completion rate, end-to-end latency, and installation reliability.

This plan is intentionally benchmark-first. It does not assume that OpenCV, visual embeddings, OCR, or any proposed selector is better. Each is a falsifiable candidate that must earn its runtime and distribution cost.

We gratefully build on Brad Bonanno's `bradautomates/claude-video`. The original design remains the named control, its history and license remain intact, and benchmark reporting must describe its strengths as carefully as its limitations.

## Verified control facts

An independent architecture pass verified these facts before optimization:

- Runtime files and tests at the planning checkpoint are byte-identical to control commit `83da59f`.
- The existing suite passes 71 tests.
- `skills/watch/SKILL.md` is 21,807 bytes and approximately 5,405 `o200k_base` tokens.
- Its instruction to review runtime scripts before first use can raise pre-video context to approximately 26,182 tokens.
- A successful `setup.py --check` measured approximately 34 ms per local invocation over 30 runs; preserve its silent sub-100 ms behavior.
- The agent parses the **Question**, but the runtime interface receives only the **Video source**, preventing runtime query-aware selection.
- Visual URL requests can run yt-dlp once for captions/metadata and again for media/captions/metadata.
- Focused local-file requests transcribe full audio before filtering the transcript range.
- Frame engines can write every candidate at reader resolution and later delete over-budget candidates.
- Cue extraction launches one FFmpeg process per timestamp, and some fallback paths repeat metadata probes.

These are baseline observations, not proof that a replacement will be better. The benchmark module must measure the effect of changing each one.

## Non-negotiable product requirements

1. Preserve the current installation experience:
   - Claude Code marketplace and plugin installation;
   - `npx skills add abe238/claude-video-plus -g` across Agent Skills hosts;
   - a release-built `watch.skill` for claude.ai;
   - manual clone and `skills/watch` symlink installation.
2. Keep `skills/watch/` self-contained and path resolution host-independent.
3. Keep successful setup preflight silent and approximately sub-100 ms.
4. Do not require a large model, OpenCV, OCR engine, vector database, or new API key for baseline operation.
5. Offer OpenCV during setup as an informed opt-in choice after explaining measured install size, latency, and expected capability tradeoffs; record the choice and do not nag users who decline.
6. Fail open to deterministic FFmpeg/caption/Whisper behavior when optional signals are unavailable.
7. Do not make a public superiority claim without the evidence and statistical gates in this plan.

## Hypotheses

| ID | Candidate change | Expected benefit | Primary risk | Required evidence |
| --- | --- | --- | --- | --- |
| H1 | Shrink `SKILL.md`; move orchestration into scripts | Fewer instruction tokens on every invocation | Hidden host-specific behavior moves into code incorrectly | Install matrix, behavior parity, prompt-token delta |
| H2 | Pass the question into the evidence compiler and retrieve transcript windows | Large text-token reduction on targeted questions | Missing relevant context | Answer non-inferiority and evidence-span recall |
| H3 | Replace last-kept 16x16 mean-difference dedup with multi-scale novelty and temporal clustering | Remove visual echoes without losing small UI/text changes | More CPU or false drops | Gold key-change recall, redundancy, latency |
| H4 | Use coarse-to-fine evidence-span refinement | Fewer frames for long, targeted questions | Search misses or extra passes | Long-video accuracy, frame tokens, p95 latency |
| H5 | Allocate resolution per evidence span and use high-resolution crops only when needed | Lower image tokens with preserved readability | Cropping away context | OCR/detail QA accuracy and pixel/token cost |
| H6 | Cache scout indexes and selected media by content identity | Faster follow-up questions | Stale or corrupt cache | Warm latency, invalidation and corruption tests |
| H7 | Download focused ranges when the question names a time span | Lower download and decode cost | Keyframe-cut inaccuracies and site variance | Timestamp accuracy, bytes, completion rate |
| H8 | Offer OpenCV as an explicit optional scoring adapter | Better motion, edge, color, and local-change signals for installers who accept the cost | 33-66 MB wheel, cold-start cost, inconsistent availability | Ablation against FFmpeg/stdlib scoring plus informed-choice and install gates |
| H9 | Optional semantic frame/OCR retrieval | Better visual-only query recall | Model downloads, privacy, platform failures | Visual QA gain exceeding cost and reliability penalties |
| H10 | Plan acquisition once per required modality | Fewer yt-dlp and metadata passes | Site-specific combined-download failures | Invocation counts, completion rate, network latency |
| H11 | Make focused transcription range-aware | Less audio processing, upload, and latency | Incorrect absolute timestamps or lost context | Range command assertions, timestamp accuracy, upload bytes |
| H12 | Batch cue extraction and reuse probed metadata | Fewer process launches and decodes | Sparse seeks may behave differently by codec | FFmpeg/ffprobe invocation counts, exact timestamp tests |

## Research foundations

The candidate algorithm should synthesize and ablate ideas from primary video-efficiency research rather than treating generic scene detection as sufficient:

- [Adaptive Keyframe Sampling (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/html/Tang_Adaptive_Keyframe_Sampling_for_Long_Video_Understanding_CVPR_2025_paper.html) formulates selection under a fixed visual-token budget using both prompt relevance and video coverage.
- [VideoTree (CVPR 2025)](https://arxiv.org/abs/2405.19209) supports training-free, query-adaptive, hierarchical coarse-to-fine refinement.
- [LongVU](https://arxiv.org/abs/2410.17434) removes redundant frames with visual features, then uses text guidance and temporal dependencies for adaptive spatial reduction.
- [Q-Frame](https://arxiv.org/abs/2506.22139) combines query-aware frame selection with multi-resolution allocation under a fixed budget.
- [FrameFusion](https://arxiv.org/abs/2501.01986) shows that similarity merging and importance pruning address different sources of visual-token waste.
- [Less is More: Adaptive Frame-Pruning (CVPR 2026 Findings)](https://openaccess.thecvf.com/content/CVPR2026F/html/Wang_Less_is_More_Token-Efficient_Video-QA_via_Adaptive_Frame-Pruning_and_Semantic_CVPRF_2026_paper.html) identifies temporally redundant "visual echoes" and combines adaptive clustering with low-cost semantic compensation, reporting up to 82.2% total-input-token reduction on its evaluated settings.
- [MeToM (CVPR 2026)](https://openaccess.thecvf.com/content/CVPR2026/html/Wu_MeToM_Metadata-Guided_Token_Merging_for_Efficient_Video_LLMs_CVPR_2026_paper.html) uses codec residual and Group-of-Pictures metadata as inexpensive content-complexity signals for adaptive allocation.
- [Rethinking RAG in Long Videos](https://arxiv.org/abs/2606.13141) argues that modality and temporal granularity should be selected per evidence chunk rather than once for an entire question.
- [ReQuest](https://arxiv.org/abs/2607.01737) adds uncertainty-triggered extra computation and adaptive temporal non-maximum suppression so difficult questions receive denser evidence without imposing that cost on every request.
- [PixelRAG](https://arxiv.org/abs/2606.28344) supports retrieving in the visual representation the reader consumes and treating resolution as a context-cost control, though its large document-index infrastructure is not a suitable mandatory dependency here.

The reported results above belong to their own models, datasets, and experimental settings. They are design evidence, not transferable performance claims for this skill.

Several methods optimize internal visual tokens inside models the skill does not control; PixelRAG evaluates web screenshots; and semantic selectors may require training or large encoders. Their results do not directly validate selecting external JPEG evidence for an agent. Recent arXiv-only work is preprint evidence until peer review. Treat codec packet/GoP size as encoder- and codec-confounded unless normalized; it is not inherently a semantic-density score.

## Implementation repository review

Popular repositories contribute useful implementation patterns, but most are too heavy to become default dependencies:

| Repository | Mechanism worth testing or borrowing | What not to import into the default path |
| --- | --- | --- |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | HSV hue/saturation/luma differences, optional edge deltas, minimum scene length, and a rolling adaptive threshold that suppresses false cuts during camera motion | Mandatory OpenCV dependency or treating scene boundaries as answer relevance |
| [TransNetV2](https://github.com/soCzech/TransNetV2) | Neural shot-boundary detection as an offline quality ceiling for the generated/curated corpus | TensorFlow/model weight requirement for normal installs |
| [Decord](https://github.com/dmlc/decord) | Batched random-access frame retrieval, duplicate-index coalescing, and decoder-aware seeking | A second mandatory native decoder alongside FFmpeg |
| [video2dataset](https://github.com/iejMac/video2dataset) | Stable sample IDs, documented incremental mode, per-sample status/error metadata, and separable reprocessing stages | Distributed dataset machinery in a single-video skill |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Batched/VAD-filtered local transcription, quantization, and lower-memory inference as a future optional transcript adapter | Bundled local model downloads or replacing caption/API fast paths by default |
| [WhisperX](https://github.com/m-bain/whisperX) | Voice-activity batching and word-level alignment for more precise deictic timestamp evaluation | PyTorch/alignment/diarization stack in the base install |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Portable local transcription backend and explicit model-size choices | Silent model downloads or making local ASR mandatory |
| [OpenCLIP](https://github.com/mlfoundations/open_clip) | Text-image relevance as an offline oracle and optional semantic adapter | PyTorch training/inference stack in the self-contained default skill |
| [AKS](https://github.com/ncTimTang/AKS) | Relevance-plus-coverage selection objective and evaluation integration | BLIP/CLIP/SeViLA/spaCy environment as runtime dependencies |
| [Adaptive Frame Pruning](https://github.com/shaoguangwang/Adaptive-Frame-Pruning) | Post-selection clustering of visual echoes and structured input/output around timestamped initial frames | CUDA/PyTorch multimodal feature stack in the default path |
| [FrameFusion](https://github.com/thu-nics/FrameFusion) | Separate similarity merging from importance pruning in ablations | Patching internal layers of a reader model the skill does not control |
| [lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval) | Public video-QA adapters, task versioning, and repeatable evaluation conventions | Its full training/evaluation dependency tree in the runtime skill |
| [Video-MME](https://github.com/MME-Benchmarks/Video-MME) and [LongVideoBench](https://github.com/longvideobench/LongVideoBench) | Held-out long-video, subtitle, and temporal-QA cases for product-level evaluation | Tuning thresholds on their final test cases |

Repository popularity is only a discovery signal. Adoption still requires license review, maintained-version pinning, a small reproducible prototype, and an ablation showing measurable leverage for this product. Perform an explicit license check before using any Tier 3 dataset or repository; GitHub metadata alone is not sufficient, and several candidate benchmark/code repositories do not expose a clear license there.

## Candidate selection algorithm

Working name: **Budgeted Multimodal Evidence Selection**. Do not describe it as novel in public until a broader prior-art review and the held-out benchmarks are complete.

### 1. Construct hierarchical evidence spans

Create coarse timeline spans from transcript pauses/chapters, codec and shot metadata, and low-resolution change signals. Subdivide only spans selected for refinement. This adapts VideoTree's hierarchy to a tool-based evidence compiler without requiring a video-language model at every level.

### 2. Score independent evidence signals

For each candidate span, calculate separately:

- question relevance from transcript and OCR lexical retrieval plus optional visual-text similarity;
- coverage value across time and parent timeline spans;
- visual novelty from multi-scale local change and cluster distance;
- motion and boundary value for temporal questions;
- modality complementarity when speech and pixels support different facts;
- information-density proxies such as codec packet/GoP size, edges, OCR density, and motion;
- reader cost at each available transcript-window, frame, crop, and resolution choice.

Keep signals separate in the evidence manifest so their value can be ablated. Do not collapse them into an opaque confidence number that cannot be diagnosed.

### 3. Select by marginal evidence value per reader cost

Choose evidence greedily under the **Evidence budget** using a submodular-style objective:

```text
marginal utility =
  question relevance
  + timeline and semantic coverage
  + modality complementarity
  + required temporal-boundary value
  - redundancy with already selected evidence

selection priority = marginal utility / incremental reader cost
```

Weights and constraints depend on the **Question** class:

- **Targeted question**: emphasize relevance and localized refinement.
- **Coverage question**: require hierarchical timeline anchors before spending remaining budget on relevance.
- Motion or state-change question: require before/after pairs or short temporal triplets.
- Visible-text question: prefer a source-linked high-resolution crop over a high-resolution full frame.
- Speech-only question: allow zero images when transcript evidence is sufficient.

The selection rule combines AKS-style relevance and coverage with FrameFusion/AFP-style redundancy control. Every term must have an ablation; complexity without measurable leverage should be deleted.

### 4. Enforce adaptive temporal diversity

Apply temporal non-maximum suppression after ranking, but make its radius depend on question type, span duration, and uncertainty. Preserve pinned timestamps, scene boundaries, before/after obligations, and coverage anchors even when nearby frames look similar.

### 5. Allocate resolution after selection

Materialize only selected timestamps. Assign low, standard, high, or cropped resolution based on expected detail value divided by reader cost. Never write thousands of reader-resolution candidates merely to delete most of them.

### 6. Expand only when uncertain

Start with the cheapest evidence set that satisfies hard coverage and temporal constraints. Expand the affected parent span when retrieval scores are flat, modalities disagree, required evidence is absent, or the question class demands more detail. Use the **Control pipeline** as the final deterministic fallback.

### 7. Prove contribution through ablation

Benchmark the cumulative algorithm and each addition independently:

1. Control pipeline.
2. Question-aware transcript retrieval only.
3. Add relevance-plus-coverage selection.
4. Add multi-signal redundancy clustering.
5. Add hierarchical refinement.
6. Add adaptive temporal diversity/uncertainty expansion.
7. Add codec complexity signals.
8. Add adaptive resolution/crops.
9. Compare standard scoring with the opt-in OpenCV adapter.

Report marginal accuracy, evidence recall, tokens, latency, memory, and install cost at every step. A feature that does not improve the Pareto frontier should not remain in the default implementation.

## Question policy

The **Question** policy is versioned benchmark input, not an unobserved model judgment.

- Accept an explicit `auto`, `targeted`, or `coverage` policy in the benchmark manifest and eventual runtime.
- In `auto`, classify with deterministic, tested rules first. Record the selected policy and rule/version in the **Evidence manifest**.
- Treat ambiguous, multipart, or low-confidence classification as `coverage` or use the **Control pipeline** fallback; never silently choose the cheapest path.
- A multipart **Question** unions the hard evidence obligations of its parts.
- Any model call used for classification or uncertainty is an explicit measured selector call, including its tokens, latency, cost, and failure mode.
- The user can override automatic classification without changing the requested analysis.

Misclassification tests are a release gate because incorrectly treating a **Coverage question** as targeted can produce a plausible but incomplete answer.

## Evidence budget and total-cost accounting

Version the **Evidence budget** as structured data rather than one ambiguous number:

```json
{
  "schema_version": 1,
  "max_text_tokens": 8000,
  "max_images": 24,
  "max_image_pixels": 6000000,
  "max_total_input_tokens": null,
  "provider_profile": "model-independent-v1",
  "overflow_policy": "record-and-fallback"
}
```

- The model-independent profile constrains text, image count, and pixels separately.
- Provider profiles add pinned tokenizer and image-accounting rules plus actual usage metadata when the host exposes it.
- Hard temporal pairs, pinned timestamps, and coverage anchors may exceed a soft budget only when the manifest records the reason and overflow. A hard provider limit must trigger refinement or a clear insufficient-budget result, not silent evidence loss.
- Map the budget to the **Control pipeline** with existing frame caps where possible. Because the control cannot retrieve transcript windows, report its transcript overflow rather than truncating or otherwise improving the control.

Define **total reader input** as all uncached input the answer model receives:

- native `SKILL.md` and any runtime scripts/instructions read;
- host or reader prompt added by the benchmark harness;
- every tool report and evidence manifest;
- transcript and OCR text;
- image tokens or, when unavailable, pinned provider estimates plus raw pixel totals;
- retry and verification context;
- every extra selector, classifier, or verifier model call reported separately and in total system cost.

Report prompt-cached and uncached usage separately. Also report CPU, API calls, local/remote model work, disk, network, and estimated dollar cost so the candidate cannot hide work outside reader tokens.

Version the **Evidence manifest** from its first introduction. Cache keys include manifest schema, scorer/model versions, source identity, policy, and relevant configuration; incompatible schemas invalidate atomically rather than migrate silently.

## Proposed deep modules

These names describe intended locality, not frozen implementation interfaces.

1. **Evidence compiler module** - owns the end-to-end transformation from video source, question, and evidence budget to an evidence manifest. This creates one test surface for behavior that is currently coordinated partly by `SKILL.md` and partly by `watch.py`.
2. **Media acquisition module** - owns caption discovery, metadata, complete or range media download, and reuse of already acquired files.
3. **Scout index module** - owns timestamped transcript chunks, low-resolution visual descriptors, shot/change metadata, cache identity, and optional adapters.
4. **Evidence selection module** - owns relevance, coverage, redundancy, temporal diversity, neighbor/boundary preservation, and coverage-question policy.
5. **Evidence rendering module** - owns final reader-ready frames, crops, resolution allocation, transcript windows, and context-cost accounting.
6. **Transcript module** - owns canonical caption/Whisper segments, conservative overlap removal, focused absolute timestamps, retrieval chunks, and transcript cache identity.
7. **Evidence store module** - owns atomic content-addressed caching, invalidation, concurrency, size limits, and privacy rules.
8. **Benchmark module** - runs control and candidate pipelines from the same cases and produces machine-readable measurements, confidence intervals, and comparison reports.

The deletion test for the evidence compiler is decisive: deleting it should force orchestration, fallbacks, budgets, and manifests back into skill instructions and callers. That complexity concentration gives the module depth, leverage, and locality.

## OpenCV decision

Do not replace FFmpeg decoding with `cv2.VideoCapture`. FFmpeg remains the media adapter because it is already required, handles more codecs consistently, and avoids a second decode path.

Evaluate three scout-scoring variants behind the benchmark module:

1. FFmpeg plus pure-stdlib multi-scale scoring;
2. FFmpeg-native filters such as scene scoring, `mpdecimate`, `freezedetect`, and `thumbnail`;
3. FFmpeg frame pipe plus optional OpenCV scoring.

OpenCV experiments may use:

- multi-scale absolute differences rather than one global 16x16 mean;
- HSV histogram distance;
- edge-map change;
- sparse optical flow for motion and transition questions;
- perceptual hashes as one signal, never the sole drop rule;
- optional DNN/ONNX relevance only in a separate ablation.

A frame may be dropped only when the selected scoring policy establishes redundancy without suppressing a required local change, temporal boundary, or coverage anchor. Before/after pairs must be preserved for action, transition, and bug-reproduction questions.

OpenCV cannot become required unless it passes every quality and speed gate, improves more than the dependency-free scorer, and remains within the install-size gate. The expected outcome is that it remains optional or experimental.

### Installer choice

Present the choice only after required binaries work, using plain language and benchmark-backed numbers:

- **Standard visual scoring (recommended default)** - FFmpeg plus standard-library Python; smallest install and identical baseline compatibility.
- **Enhanced visual scoring with OpenCV** - installs `opencv-python-headless` only after explicit consent; may add stronger color, edge, local-change, and motion signals at the cost of a larger dependency and possible cold-start overhead.

Do not require `opencv-contrib-python-headless` merely for perceptual hashing; first benchmark whether equivalent small hashes can be implemented with the standard OpenCV wheel or dependency-free code. Store the explicit choice as `WATCH_VISION_BACKEND=stdlib|opencv`. If `opencv` is selected but unavailable, report the fallback once, use the standard adapter, and provide a repair command. Allow changing the choice later without reinstalling the skill.

Setup text must distinguish measured results from hypotheses. Until the OpenCV ablation exists, label it experimental rather than claiming it improves recognition.

Avoid modifying the host Python environment. On surfaces where persistent Python environments are supported, create a versioned virtual environment under `~/.cache/watch/venvs/opencv/<opencv-version>-<python-abi>-<platform-tag>-<helper-protocol>/` and install the pinned wheel there after consent. Invoke a bundled OpenCV helper with that environment's interpreter and exchange versioned JSON, leaving the main runtime on standard Python. This avoids PEP 668 conflicts and mismatched imports. Keep optional runtime environments outside evidence-cache purge roots.

The OpenCV installer contract must specify supported Python/OS/architecture wheels, proxy and offline behavior, checksums or package hashes, repair, upgrade, and uninstall. Where persistent package installation is unavailable, including constrained claude.ai execution environments, show OpenCV as unsupported for that surface and continue with standard scoring. Any import, helper, or protocol failure falls back deterministically and is recorded in the manifest.

## Benchmark corpus

### Tier 1: deterministic generated cases

Build small videos with FFmpeg and checked-in generation recipes. Store recipes and gold annotations, not large generated binaries.

Include:

- identical and recompressed frames;
- brightness changes and fades;
- one-character and one-line slide changes;
- terminal scrolling and cursor movement;
- held slides with changing subtitles;
- rolling-overlap WebVTT captions and legitimate repeated speech;
- scene cuts with equal average luminance;
- small objects entering or leaving;
- slow motion, fast motion, and camera motion;
- before/after UI state transitions;
- cue/detail timestamp collisions and repeated visuals separated by long intervals;
- variable-frame-rate, long-GOP, rotated, vertical, odd-dimension, and non-square-pixel media;
- focused ranges at keyframe boundaries and the final frame;
- corrupt/truncated media, interrupted writes, and cache corruption;
- deictic transcript cues, ambiguous/multipart questions, and impossible budgets;
- silence, speech, missing audio, and missing captions.

Every case must have exact gold timestamps, required frames or intervals, and expected duplicate groups.

### Tier 2: curated real-world cases

Create a manifest of redistributable or URL-addressed videos covering:

- lectures and slide decks;
- screen-recorded bug reproductions;
- talking-head and podcast video;
- high-motion footage;
- tutorials with important visible text;
- long videos with narrow questions;
- multilingual and caption-less sources.

Explicitly include or declare unsupported sound-event questions. Current English-caption acquisition must not silently define multilingual scope; language selection and fallback behavior are benchmark inputs.

Pin source identity, duration, checksum when downloaded, license, and gold evidence spans. Keep network end-to-end results separate from predownloaded media results.

Freeze Tier 2/3 item selection, class weighting, gold annotations, and primary metrics before tuning thresholds. Tier 1 is diagnostic and may target known risks; never present Tier 1 alone as evidence of general superiority.

### Tier 3: public video-QA subsets

Use stable, license-compatible subsets of long-video and temporal-QA benchmarks. Record dataset version and item IDs. Do not tune thresholds on the final test split.

### Question classes

Every tier should cover:

- transcript-only;
- visual-only;
- cross-modal;
- exact timestamp;
- temporal order or before/after;
- targeted long-video retrieval;
- coverage summary;
- unanswerable or insufficient-evidence questions.

## Measurements

### Evidence quality

- Evidence-span Recall@budget against gold intervals.
- Temporal intersection-over-union for localized answers.
- Recall of required before/after frame pairs.
- Duplicate-group compression and false-drop rate.
- Coverage across timeline quantiles for coverage questions.

### Answer quality

- Exact match or task-specific scoring where available.
- Blinded semantic grading for open answers using a frozen rubric.
- Timestamp correctness and citation support.
- Unsupported-claim and unanswerable-question behavior.

### Context cost

- Loaded `SKILL.md` bytes and tokenizer-specific tokens.
- Transcript characters and actual reader text tokens.
- Frame count, dimensions, total pixels, encoded bytes, and actual reader image tokens.
- Total reader input tokens from provider usage metadata when available.
- Number of reader/model calls.

### Performance

- Media bytes downloaded.
- Decode and extraction CPU time.
- End-to-end wall time, p50, p95, and maximum.
- Peak resident memory.
- Cold run, warm cache, and follow-up question latency.
- Optional dependency/model initialization time reported separately.

### Reliability and distribution

- Task completion rate.
- Exit codes and categorized failure modes.
- Recovery with missing captions, audio, OCR, OpenCV, embeddings, network, or corrupt cache.
- Install, first-run, update, invocation, and uninstall success on supported surfaces.
- Skill bundle size and mandatory download size.
- OpenCV opt-in, decline, missing-package fallback, repair, and later backend-switch behavior.

## Experimental protocol

### Two comparison layers

Run both layers because neither alone is fair or complete:

1. **Pipeline comparison** - convert the native control Markdown report into the versioned canonical **Evidence manifest** without dropping, summarizing, resizing, or reordering any control evidence. Feed control and candidate manifests to one frozen reader prompt. This isolates acquisition/selection/rendering quality from skill-instruction changes.
2. **Product comparison** - invoke each native `SKILL.md` through the same pinned host and reader harness. Capture every instruction or script read, tool result, image, retry, and usage record. Follow each skill contract literally, including the control instruction to review scripts, and report alternate observed-host behavior only as a separate sensitivity analysis.

The control adapter may normalize representation but must never improve control selection. Golden cases assert lossless control conversion.

### Execution

1. Create isolated worktrees for control `83da59f` and the candidate commit.
2. Run both from clean environments against identical case manifests and **Evidence budgets**.
3. Pin FFmpeg, yt-dlp, Python, OS/architecture, host version, reader model version, prompts, temperature, evaluator rubric, and provider accounting profile.
4. Predownload media for core pipeline measurements; run a separate randomized network suite with retries and failure reporting.
5. Randomize control/candidate order and blind answer graders to pipeline identity.
6. Distinguish three warm states:
   - cold run with no local or reader cache;
   - same-task follow-up where control evidence may already remain in reader context;
   - new-task warm local cache where neither pipeline gets free reader context.
7. Report per-class and duration-bucket results, not only an overall mean. A gain on transcript QA must not hide a regression on UI changes or motion.
8. Publish raw JSONL case results, environment metadata, summary tables, adapter logs, and the exact comparison command.

### Statistical design

- Run a preregistered pilot to estimate paired variance before fixing final non-inferiority sample sizes.
- Use the video or correlated video-question group as the independent resampling unit, never individual repeated model runs.
- Stratify the paired bootstrap by question class and duration bucket; use 95% confidence intervals.
- Treat answer quality, evidence-span recall, total reader input, p95 latency, and completion rate as primary endpoints. Apply Holm correction to families of secondary comparisons.
- State the minimum detectable effect and powered sample count for each primary endpoint. Repeated model runs, at least three when available, estimate within-case variance but do not replace independent videos.
- Target a 2-percentage-point overall quality non-inferiority margin. Use a wider per-class safety margin only when the powered pilot requires it, preregister it before held-out evaluation, and report that limitation prominently.
- Never report only the best run or change thresholds after viewing held-out results.

## Acceptance gates

Targets are design goals, not current claims.

### Quality and reliability

- Candidate answer accuracy and evidence-span recall meet the preregistered, pilot-powered non-inferiority margins; the design target is 2 percentage points overall.
- Per-class point estimates worse by more than 5 points are blocking safety signals even when a class is underpowered; collect more cases rather than average the regression away.
- Timestamp accuracy meets its preregistered absolute-error and temporal-IoU margins.
- Required local-change and before/after cases have zero known false drops in the deterministic tier.
- Completion rate is at least the control rate in every supported environment.

### Token savings

- At least 50% median total reader-input reduction on targeted questions.
- At least 25% median reduction on coverage questions without reducing timeline coverage or answer quality.
- No question class may increase median reader input without a measured quality gain that is reported explicitly.

### Performance

- Warm p95 end-to-end latency is no slower than control.
- Cold p95 is within the larger of 5% or 250 ms of control in each duration bucket unless the user explicitly enables an optional adapter with a documented tradeoff.
- Focused URL requests reduce or match downloaded bytes and do not regress timestamp accuracy.

### Installation

- 100% success in deterministic offline artifact, copied-layout, symlink-layout, and preflight tests for the declared support matrix. Network marketplace/update tests report retries and confidence separately.
- Keep the compressed default `watch.skill` below 250 KB, include no wheels/models/binaries, report percentage growth from the approximately 36.6 KB control artifact, and require explicit review for any increase over 100 KB.
- No new mandatory model download or API key.
- Successful repeat preflight remains approximately sub-100 ms.

If a change fails a gate, keep it experimental, revise it, or delete it. Do not compensate for a quality regression by pointing only to token savings.

## Implementation sequence

Each phase lands separately and reruns the control comparison.

### Phase 0: preregister and build the benchmark module

- 0A: freeze case, gold-annotation, **Evidence budget**, and result schemas.
- 0B: implement the lossless control-to-manifest adapter and golden parity tests.
- 0C: implement the two-layer worktree/host runner and total-cost instrumentation.
- 0D: add generated recipes, curated manifests, and failure-injection cases.
- 0E: run the pilot, power analysis, and preregistered statistical report.

### Phase 1: introduce the evidence manifest with parity

- Add the versioned manifest and control-equivalent candidate output without changing selected evidence.
- Preserve setup remediation, errors, cleanup guidance, path resolution, and silent repeat preflight.
- Validate copied, symlinked, and bundled layouts.

### Phase 2: shrink only the skill interface

- Move deterministic orchestration behind the evidence compiler module.
- Remove first-use script-review requirements only after release and behavior tests cover them.
- Measure prompt savings separately from evidence changes.

### Phase 3: add the question seam and policy only

- Pass the complete **Question** and explicit/automatic policy into the evidence compiler.
- Preserve control evidence until retrieval lands.
- Test ambiguity, multipart requests, user override, and conservative fallback.

### Phase 4: add transcript retrieval only

- Canonicalize and test VTT/Whisper segments.
- Add dependency-free lexical retrieval and selected transcript windows.
- Preserve complete transcript evidence for **Coverage questions**.

### Phase 5: add focused transcription only

- Extract/transcribe requested audio ranges before upload or local inference.
- Preserve absolute timestamps and partial failure behavior.

### Phase 6: add focused media range acquisition only

- Use section download where supported and preserve full-download fallback.
- Test long-GOP/keyframe edges, final-frame ranges, and site variance.

### Phase 7: consolidate acquisition only

- Plan captions, metadata, audio, and video from required modalities.
- Eliminate repeated yt-dlp work without changing evidence.

### Phase 8: batch point extraction and metadata reuse only

- Batch cue timestamps where benchmarks show a gain.
- Reuse already-probed metadata and record process counts.

### Phase 9: separate scout selection from final rendering

- 9A: add multi-scale local-change fixtures and raw scout measurements.
- 9B: compare one-pass full-resolution and two-stage low-resolution adapters.
- 9C: compare standard, FFmpeg-native, and OpenCV scorers.
- 9D: add temporal clustering, cue/detail collision handling, and required neighbor pairs.
- Offer the installer choice only after the scorer ablation states real tradeoffs.

### Phase 10: add the evidence store

- Add content-addressed cache keys, atomic writes, locks, permissions, corruption handling, size limits, purge, and schema invalidation.
- Update user-facing persistence/privacy documentation before enabling it.
- Benchmark cold, same-task follow-up, and new-task warm states fairly.

### Phase 11: add coarse-to-fine selection

- 11A: add relevance-plus-coverage selection with control fallback.
- 11B: add hierarchical refinement as a separate ablation.
- 11C: add adaptive diversity and uncertainty expansion as separate ablations.
- Preserve uniform anchors for **Coverage questions** throughout.

### Phase 12: add adaptive resolution and crops

- Account for context cost before materialization.
- Add source-linked crop provenance and readability/exactness tests.

### Phase 13: add optional adapters

- Offer OpenCV only after its ablation provides real installer tradeoffs.
- Evaluate OCR, semantic embeddings, and local ASR separately.
- Keep all optional runtimes isolated from the base interpreter and default bundle.

### Phase 14: distribution identity and release decision

- Update derivative manifests, marketplace metadata, repository links, and exact install/update commands while preserving upstream attribution.
- Automate version synchronization, exactly-one-SKILL artifact structure, executable scripts, copied/symlinked layouts, and update-from-prior-version tests.
- Run the held-out suite and ask an independent agent to reproduce from a fresh clone.
- Publish limitations and per-class results; change the default only after every gate passes.

## Installation smoke-test matrix

These are Phase 14 target commands; current manifests still identify the upstream control and must not be presented as derivative release metadata until that phase is complete. Test from a clean environment:

| Surface | Install | Update or rebuild | Required assertion |
| --- | --- | --- | --- |
| Claude Code | `/plugin marketplace add abe238/claude-video-plus`, then `/plugin install watch@claude-video-plus` | `/plugin update watch@claude-video-plus` | derivative identity and upstream attribution are both clear; `/watch` resolves self-contained scripts |
| Agent Skills hosts | `npx skills add abe238/claude-video-plus -g` | `npx skills update watch -g` | discovered skill includes all runtime files |
| Targeted Agent Skills host | `npx skills add abe238/claude-video-plus -a codex` | `npx skills update watch -a codex` | host-specific install path works |
| claude.ai artifact | download the derivative release `watch.skill` | `bash skills/watch/scripts/build-skill.sh` | archive root and executable scripts are valid |
| Manual development | clone `abe238/claude-video-plus` + symlink `skills/watch` | `git pull` | relative script resolution survives symlink |
| Optional OpenCV | opt in during setup | repair or switch backend | decline keeps baseline working; failure falls back deterministically |

Initial declared base matrix: current supported Python versions on macOS arm64/x86_64, Ubuntu x86_64, and Windows x86_64, with FFmpeg/ffprobe and yt-dlp available as documented. Test representative Claude Code, Codex, Cursor, and manual layouts; validate the Agent Skills artifact contract for other hosts rather than claiming direct execution on all 50+. Expand the matrix only when CI or a recorded manual run exists.

Offline deterministic layout/preflight tests must pass 100%. Run marketplace, private/public GitHub access, package-manager, and update tests separately because they depend on external services; record attempts, retries, and confidence. Optional adapters must not change default install success.

## Review instructions for another agent

The reviewer should:

1. Verify `83da59f` is the untouched upstream ancestor and suitable control.
2. Inspect whether every claimed metric can be collected without favoring the candidate.
3. Challenge the corpus for missing video/question classes and leakage.
4. Check that non-inferiority and confidence rules prevent cherry-picking.
5. Verify installation and failure-injection gates are first-class, not afterthoughts.
6. Identify any phase that changes behavior before the harness can measure it.
7. Recommend deletions where a proposed dependency or module lacks measurable leverage.
8. Return blocking concerns separately from optional improvements.

The first independent review found blockers in comparison fairness, budget accounting, statistical power, phase attribution, and optional installation. After revision, the second review returned no blockers and a **READY for Phase 0** verdict. This does not authorize optimization or superiority claims before the benchmark gates pass.

## Contribution workflow

Current owner-directed work may be committed directly to `main` at coherent, tested checkpoints. If another person contributes in the future, use a branch and pull request so benchmark evidence, attribution, implementation, and review remain inspectable.

## Evidence required for a public claim

Any README or release claim that the candidate is better must link to:

- control and candidate commit hashes;
- corpus manifest and dataset versions;
- environment lock information;
- exact reproduction command;
- raw paired results;
- summary with confidence intervals;
- known regressions, exclusions, and failed cases.

Until those artifacts exist, describe all expected improvements as hypotheses.
