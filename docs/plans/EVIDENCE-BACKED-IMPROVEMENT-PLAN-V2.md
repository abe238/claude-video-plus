# Evidence-backed improvement plan (v2)

Status: Independently reviewed via adversarial multi-lens critique; ready for Milestone A implementation

Control: unmodified upstream commit `83da59f`

Candidate: commits derived from the control in `abe238/claude-video-plus`

This document supersedes the *sequencing, gating, and module-scope* decisions in [`EVIDENCE-BACKED-IMPROVEMENT-PLAN.md`](EVIDENCE-BACKED-IMPROVEMENT-PLAN.md) after those decisions failed an adversarial review. It does not replace that file; both stay in the repository. Where a section below is silent on a change, the v1 text still applies.

## Adversarial review summary

This plan was rewritten after v1 went through a five-lens adversarial review (statistical/methodological rigor, engineering scope/YAGNI, product/user value, research literature, distribution/maintenance) plus a second research sweep that independently surfaced agentic video-QA prior art the first pass missed. The reviews converged on one structural finding from three independent directions at once: v1's 15-phase, full-statistical-machinery-at-every-phase structure creates repeated looks at whatever corpus backs the gate reruns (a multiplicity/optimizer's-curse problem the statistics lens flagged), applies RCT-grade process to mechanical low-risk changes (the scope/YAGNI lens's objection), and sizes a research-team-scale labor tax for a solo maintainer (the distribution/maintenance lens's objection). Because three unrelated failure modes point at the same mechanism, this plan's single biggest change is collapsing the 15 phases (Phase 0-14) into 4 milestones (A-D), each closed by one full statistical confirmatory gate, with a cheap deterministic parity check running on every commit in between. Every other adopted finding is only cheap and sustainable because this restructuring makes full-rigor runs rare instead of routine.

Also adopted: a development-slice/confirmatory-slice corpus split so milestone consolidation doesn't just reduce the frequency of peeking at held-out data but actually zeroes out the multiplicity problem at the final release decision; grader-instrument validation (measurement error plus a blinding-leak check) before that final run; a per-class CI-bound safety gate scoped to the final gate only, paired with a stated minimum-cases stopping rule so it cannot stall the project indefinitely; full reader-input token *distribution* reporting from day one with the p95 tail promoted to a hard blocking gate only once real data exists to set a sane threshold; an explicit statement that the plan's two comparison layers (pipeline and product) are both binding and reported side by side, closing a cherry-picking gap; a "cheapest mode a competent user would already pick" comparison column on every token/latency gate; a reported-not-gated precision metric for hype/padding-exclusion questions; a named "reader-model epoch" tag so a hosted-reader deprecation cannot silently invalidate a comparison; and a new agentic-video-QA research subsection.

Also cut, per the same convergence: the OpenCV installer collapses from a versioned-venv/helper-protocol subsystem to a documented environment-variable opt-in, deferred to earn the fuller installer only if its own ablation (now inside Milestone C) shows a sustained win — v1 committed to the full installer specification ahead of evidence, writing the versioned-venv/helper-protocol contract into the standing plan before the ablation that would justify it had produced any data. The eight "proposed deep modules" collapse to three (Evidence compiler, a minimal Evidence store, the Benchmark module); the other five stay folded into existing files until a milestone-boundary deletion-test reapplication demands extraction. Tier 3 of the benchmark corpus is deferred out of the per-phase gating loop entirely, run once before any public "beats baselines" claim. The fixed-per-class-margin idea is downgraded from a required change to a soft recommendation — the existing preregister-before-held-out and disclosure rules already block its main failure mode, and forcing it now risks making some question classes permanently unshippable for no proportionate gain.

Three findings were explicitly rejected rather than adopted, named here for the transparency record: a standing local open-weights reader-model anchor (a second permanently-maintained inference stack, justified by a hedge its own proposer doubts will correlate with the hosted grader); naming six specific small Hugging Face models (SmolVLM2, Moondream2, GOT-OCR2.0, bge-small-en-v1.5, siglip2-base, Moonshine-Streaming-Tiny) in this standing document ahead of the ablation that would actually decide among them (they remain legitimate candidates — H8/H9 for the vision, OCR, and embedding models, the unhypothesized local-ASR adapter slot in Milestone D for Moonshine — to be named when Milestone C/D scopes those ablations, not now); and importing DoraemonGPT's MCTS tool-call search or LongVideoAgent's RL-trained master-agent policy as design inputs, since both add a new self-sustaining engineering surface (search-and-planning, or RL training) that nothing in this plan's falsifiability standard currently requires.

Two follow-up documentation edits are recorded here as to-dos rather than executed by this document: `docs/adr/0001-opencv-is-an-optional-adapter.md` should note that a documented env-var opt-in satisfies its "explain measured tradeoffs" intent until the Milestone C ablation justifies more (the ADR-vs-first-run-friction tension the product lens raised dissolves once the installer itself is this thin, so no separate mechanism is needed); and `docs/ARCHITECTURE.md`'s "Why this is different" section should extend the existing PixelRAG internal-vs-external hedge to VideoTree and LongVU. A separate, contingent item lives inside this document, not in ARCHITECTURE.md: name an externally-computable proxy signal for FrameFusion's attention-derived importance score and MeToM's GoP signal in the Candidate selection algorithm's step 2/3 bullets once one is identified and benchmarked (see the recorded to-do in Research foundations). *(Executed at ship time, 2026-07-11: the ADR note and the ARCHITECTURE.md hedge extension both landed; the proxy-signal item remains pending.)*

## Objective

Reduce total reader-context usage while matching or improving the control pipeline's answer quality, evidence grounding, completion rate, end-to-end latency, and installation reliability.

This plan is intentionally benchmark-first. It does not assume that OpenCV, visual embeddings, OCR, or any proposed selector is better. Each is a falsifiable candidate that must earn its runtime and distribution cost.

We gratefully build on Brad Bonanno's `bradautomates/claude-video`. The original design remains the named control, its history and license remain intact, and benchmark reporting must describe its strengths as carefully as its limitations.

## Verified control facts

Unchanged from v1, where an independent architecture pass verified these facts before optimization; carried forward without modification because no adversarial finding touched them.

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

Requirement 5 is revised; every other requirement is unchanged from v1.

1. Preserve the current installation experience:
   - Claude Code marketplace and plugin installation;
   - `npx skills add abe238/claude-video-plus -g` across Agent Skills hosts;
   - a release-built `watch.skill` for claude.ai;
   - manual clone and `skills/watch` symlink installation.
2. Keep `skills/watch/` self-contained and path resolution host-independent.
3. Keep successful setup preflight silent and approximately sub-100 ms.
4. Do not require a large model, OpenCV, OCR engine, vector database, or new API key for baseline operation.
5. **(Revised)** Offer OpenCV as a documented, explicit opt-in — a stated environment variable plus a one-line manual install command with measured install-size, latency, and capability-tradeoff numbers in the documentation — rather than an interactive setup prompt. Record the choice and do not nag users who decline. The fuller versioned-venv/helper-protocol installer described in v1 is deferred behind its own ablation (Milestone C / old Phase 9C) and only replaces this documented opt-in if that ablation shows a sustained win proportionate to the added installer complexity.
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
| H6 | Cache scout indexes and selected media by content identity | Faster follow-up questions **- caveat: 4 of the 5 documented real-world `/watch` use cases (README "What people actually use it for") are single-question-per-video, so the amortization argument this hypothesis rests on may not hold by default; the risk that Scout should not run unconditionally is tracked here, not buried in an implementation note** | Stale or corrupt cache; unvalidated amortization benefit | Warm latency, invalidation and corruption tests, and a usage-weighted check of how often a second question actually arrives per video |
| H7 | Download focused ranges when the question names a time span | Lower download and decode cost | Keyframe-cut inaccuracies and site variance | Timestamp accuracy, bytes, completion rate |
| H8 | Offer OpenCV as an explicit optional scoring adapter | Better motion, edge, color, and local-change signals for installers who accept the cost | 33-66 MB wheel, cold-start cost, inconsistent availability | Ablation against FFmpeg/stdlib scoring plus informed-choice and install gates |
| H9 | Optional semantic frame/OCR retrieval | Better recall on visual-only questions | Model downloads, privacy, platform failures | Visual QA gain exceeding cost and reliability penalties |
| H10 | Plan acquisition once per required modality | Fewer yt-dlp and metadata passes | Site-specific combined-download failures | Invocation counts, completion rate, network latency |
| H11 | Make focused transcription range-aware | Less audio processing, upload, and latency | Incorrect absolute timestamps or lost context | Range command assertions, timestamp accuracy, upload bytes |
| H12 | Batch cue extraction and reuse probed metadata | Fewer process launches and decodes | Sparse seeks may behave differently by codec | FFmpeg/ffprobe invocation counts, exact timestamp tests |

H6's caveat feeds Milestone C: rather than a new mechanism, evaluate a narrow, on-demand Scout short-circuit for clearly localized questions during Milestone C's selection ablations, reusing the focused-range machinery H7 lands in Milestone B (see Implementation sequence).

## Research foundations

The candidate algorithm should synthesize and ablate ideas from primary video-efficiency research rather than treating generic scene detection as sufficient:

- [Adaptive Keyframe Sampling (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/html/Tang_Adaptive_Keyframe_Sampling_for_Long_Video_Understanding_CVPR_2025_paper.html) formulates selection under a fixed visual-token budget using both prompt relevance and video coverage.
- [VideoTree (CVPR 2025)](https://arxiv.org/abs/2405.19209) supports training-free, query-adaptive, hierarchical coarse-to-fine refinement.
- [LongVU](https://arxiv.org/abs/2410.17434) removes redundant frames with visual features, then uses text guidance and temporal dependencies for adaptive spatial reduction.
- [Q-Frame](https://arxiv.org/abs/2506.22139) combines query-aware frame selection with multi-resolution allocation under a fixed budget.
- [FrameFusion](https://arxiv.org/abs/2501.01986) shows that similarity merging and importance pruning address different sources of visual-token waste.
- [Less is More: Adaptive Frame-Pruning (CVPR 2026 Findings)](https://openaccess.thecvf.com/content/CVPR2026F/html/Wang_Less_is_More_Token-Efficient_Video-QA_via_Adaptive_Frame-Pruning_and_Semantic_CVPRF_2026_paper.html) identifies temporally redundant "visual echoes" and combines adaptive clustering with low-cost semantic compensation, reporting up to 82.2% total-input-token reduction on its evaluated settings.
- [MeToM (CVPR 2026)](https://openaccess.thecvf.com/content/CVPR2026/html/Wu_MeToM_Metadata-Guided_Token_Merging_for_Efficient_Video_LLMs_CVPR_2026_paper.html) uses codec residual and Group-of-Pictures metadata as inexpensive content-complexity signals for adaptive allocation.
- [Rethinking RAG in Long Videos](https://arxiv.org/abs/2606.13141) argues that modality and temporal granularity should be selected per **Evidence span** rather than once for an entire question.
- [ReQuest](https://arxiv.org/abs/2607.01737) adds uncertainty-triggered extra computation and adaptive temporal non-maximum suppression so difficult questions receive denser evidence without imposing that cost on every request.
- [PixelRAG](https://arxiv.org/abs/2606.28344) supports retrieving in the visual representation the reader consumes and treating resolution as a context-cost control, though its large document-index infrastructure is not a suitable mandatory dependency here.

### Agentic / tool-orchestrated video-QA (new)

A second research sweep, run specifically to find prior art for this plan's Scout -> Retrieve -> Verify shape and its "expand only when uncertain" step, surfaced agentic video-QA work that is a closer structural analog than the internal-token-compression papers above. These citations replace those papers as the primary prior art for step 6 and for the overall three-stage design; the internal-token papers above remain relevant to resolution/pruning mechanics within a stage, not to the orchestration shape itself.

- [Deep Video Discovery](https://arxiv.org/abs/2505.18079) (NeurIPS 2025, peer-reviewed, training-free) — the closest structural analog found: an LLM agent plans over its own observation state each turn and calls discrete, auditable retrieval tools (clip search, a Frame Inspect tool that VQAs a temporal sub-range, subtitle search) against an indexed evidence store, never opening the reader model's weights. 74.2% on LVBench (76.0% with transcripts). Cited as primary prior art for the overall Scout -> Retrieve -> Verify orchestration shape: unlike the internal-token-compression papers in the list above, it decides *what evidence to hand the reader* rather than *what to do with tokens inside the reader*, and does so through discrete, auditable tools over an indexed evidence store.
- [Active Video Perception](https://arxiv.org/abs/2512.05774) (Salesforce Research — Niebles, Savarese, Bansal, et al.; v2 2026-06-04) — a Planner/Observer/Reflector loop that maps directly onto Scout/Retrieve/Verify: the Planner proposes a targeted video interaction, the Observer extracts timestamped evidence, the Reflector judges sufficiency and decides whether another round is needed. Reports beating the best prior *agentic* baseline (not an internal-compression baseline) by 5.7% average accuracy across five benchmarks while using only 18.4% of inference time and 12.4% of input tokens. Cited as concrete prior art for the Verify stage's stopping/sufficiency check (step 6) and as the strongest available cost-normalized evidence that an iterative plan-observe-reflect loop can beat prior agentic approaches at a fraction of the inference time and input tokens on its evaluated settings.
- [DIG (Divide, then Ground)](https://arxiv.org/abs/2512.04000) (v2, revised 2026-03-24) — independent evidence that uniform sampling matches query-aware frame selection on *global* queries, and only *localized* queries benefit from query-aware selection, validated up to 256 frames on three long-form video-QA benchmarks. This is a **falsifiable, scope-reducing** design input, not scope-adding: it directly informs gating hierarchical coarse-to-fine refinement (Candidate selection algorithm step 1, and the old Phase 11B ablation now inside Milestone C) to **Targeted questions only**, leaving Coverage questions on the existing uniform/hierarchical-anchor path.
- [MemoryCard](https://arxiv.org/abs/2606.05917) (2026-06-04) — critiques prior query-aware selection methods for treating isolated frames as the evidence unit, and instead retrieves semantically coherent event-level "Memory Cards," reporting up to 21.8% relative accuracy improvement at comparable visual-token budgets. Cited as independent validation of this plan's own choice to make the base evidence unit an **Evidence span** rather than an isolated frame. Worth one ablation on the coverage suite (Milestone C) to see whether span-level aggregation reproduces any of its claimed gain before citing it as support rather than motivation.

The reported results above belong to their own models, datasets, and experimental settings. They are design evidence, not transferable performance claims for this skill.

Several methods optimize internal visual tokens inside models the skill does not control; PixelRAG evaluates web screenshots; and semantic selectors may require training or large encoders. Their results do not directly validate selecting external JPEG evidence for an agent. Recent arXiv-only work is preprint evidence until peer review — Deep Video Discovery is the one exception among the agentic citations above with a stated peer-reviewed venue (NeurIPS 2025). Treat codec packet/GoP size as encoder- and codec-confounded unless normalized; it is not inherently a semantic-density score.

**Recorded to-do:** `docs/ARCHITECTURE.md`'s "Why this is different" section hedged only PixelRAG as internal-vs-external; extend that same hedge to VideoTree and LongVU *(executed at ship time, 2026-07-11)*. Separately, name the externally-computable proxy signal that stands in for FrameFusion's attention-derived importance score and MeToM's GoP signal in the Candidate selection algorithm's step 2/3 bullets below — no such signal was verified in this review, so step 2/3 keep the original codec/edge/OCR-density proxies unchanged until one is identified and benchmarked *(still pending)*.

**Tier 3 versioning:** pin exact dataset revisions (the mechanism popularized by Hugging Face Hub's `revision` parameter for datasets and models) alongside the last-verified-date and license-status field described in Benchmark corpus, rather than tracking Tier 3 sources by mutable URL or branch name.

## Implementation repository review

Unchanged from v1; no adversarial finding targeted this section. Popular repositories contribute useful implementation patterns, but most are too heavy to become default dependencies:

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

**DIG-informed constraint (new):** subdivide only for **Targeted questions**. DIG's finding that query-aware selection helps localized queries and adds nothing on global/coverage queries means hierarchical refinement for **Coverage questions** stays on the existing uniform/hierarchical-anchor path (see step 6 and the Question policy) rather than subdividing by relevance score. Treat this constraint itself as falsifiable and re-check it against the Milestone C ablation before hardening it further.

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

Report marginal accuracy, evidence recall, tokens, latency, memory, and install cost at every step. A feature that does not improve the Pareto frontier should not remain in the default implementation. This ablation ladder is the full-protocol work that runs at the end of **Milestone C** (see Implementation sequence), not at every individual commit.

## Question policy

Unchanged from v1; no adversarial finding targeted this section.

The **Question** policy is versioned benchmark input, not an unobserved model judgment.

- Accept an explicit `auto`, `targeted`, or `coverage` policy in the benchmark manifest and eventual runtime.
- In `auto`, classify with deterministic, tested rules first. Record the selected policy and rule/version in the **Evidence manifest**.
- Treat ambiguous, multipart, or low-confidence classification as `coverage` or use the **Control pipeline** fallback; never silently choose the cheapest path.
- A multipart **Question** unions the hard evidence obligations of its parts.
- Any model call used for classification or uncertainty is an explicit measured selector call, including its tokens, latency, cost, and failure mode.
- The user can override automatic classification without changing the requested analysis.

Misclassification tests are a release gate because incorrectly treating a **Coverage question** as targeted can produce a plausible but incomplete answer.

## Evidence budget and total-cost accounting

Unchanged from v1; no adversarial finding targeted this section directly (the new p95/tail reporting requirement lives in Measurements, and the two-layer binding rule lives in Experimental protocol, since both are reporting/policy additions over the same accounting defined here).

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

**Revised.** v1 named eight modules before any of the underlying capability existed; only the Evidence compiler had an argued deletion test, and this repository's own domain conventions reject naming scaffolding ahead of proven necessity. Commit to three now; fold the rest into existing files until a milestone-boundary deletion-test reapplication demands extraction.

1. **Evidence compiler module** — owns the end-to-end transformation from video source, question, and evidence budget to an evidence manifest. This creates one test surface for behavior that is currently coordinated partly by `SKILL.md` and partly by `watch.py`. The deletion test is decisive: deleting it should force orchestration, fallbacks, budgets, and manifests back into skill instructions and callers. That complexity concentration gives the module depth, leverage, and locality.
2. **Evidence store module (minimal)** — a content-hash-keyed cache with no locking, no purge, and no corruption-handling in its first form; unbounded growth and no concurrency safety are a documented, deliberate simplification, not an oversight. `SKILL.md` already tells the agent to reuse in-context results within a session, so part of the problem a full cache subsystem would solve may already be handled — build the minimal version first and let real warm-latency data (Milestone B) justify locks/purge/corruption-handling later. Ship a `--no-cache` flag alongside it from the start: it is a near-zero marginal addition to code already being written, and it closes a real privacy gap for sensitive one-off recordings (bug-repro clips, unlisted screen recordings) that a persistent cache would otherwise retain by default.
3. **Benchmark module** — runs control and candidate pipelines from the same cases and produces machine-readable measurements, confidence intervals, and comparison reports. Cross-cutting from the start (Milestone A), same as v1.

**Deferred, not deleted:** Media acquisition, Scout index, Evidence selection, Evidence rendering, and Transcript stay folded into `watch.py` and its existing sibling scripts until a milestone boundary's deletion-test reapplication shows one of them has accumulated enough coordinated complexity to earn its own module boundary. Naming them now, before that complexity exists, would be scaffolding for later — exactly what this repository's own domain conventions (`docs/agents/domain.md`) and this plan's own deletion-test standard argue against.

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

### Installer choice (revised)

v1 fully specified the versioned-venv/helper-protocol installer contract in the standing plan before the ablation that decides whether OpenCV earns its keep (old Phase 9C, now inside Milestone C) had produced any evidence — design commitment ahead of justification, even though the offering itself was correctly scheduled after the ablation. This plan specifies only the documented opt-in until that ablation justifies more:

- **Standard visual scoring (default, no setup change)** — FFmpeg plus standard-library Python; smallest install and identical baseline compatibility. No interactive prompt.
- **Enhanced visual scoring with OpenCV (documented opt-in)** — set `WATCH_VISION_BACKEND=opencv` and run a documented one-line `pip install --user opencv-python-headless` (or the platform-appropriate equivalent). Documentation states measured install size, cold-start cost, and expected capability tradeoffs from the Milestone C ablation once it exists; until then, label OpenCV experimental and undocumented-benefit rather than claiming it improves recognition.

This is weaker isolation than v1's versioned virtual environment (real PEP 668 friction is possible on some hosts) and that risk is accepted as non-blocking: deterministic fallback to standard scoring is already a non-negotiable requirement (product requirement 6) regardless of installer sophistication. If `opencv` is selected but unavailable or fails to import, report the fallback once, use the standard adapter, and point to the repair command in the documentation. Allow changing `WATCH_VISION_BACKEND` later without reinstalling the skill.

**Deferred, not deleted — the full installer contract:** if Milestone C's ablation (variant 3 above, scored against variants 1-2) shows OpenCV earns a sustained win proportionate to the added complexity, build the fuller versioned-venv/helper-protocol installer described in v1: a versioned virtual environment under `~/.cache/watch/venvs/opencv/<opencv-version>-<python-abi>-<platform-tag>-<helper-protocol>/`, a bundled helper invoked through that environment's interpreter with versioned JSON exchange, and a full contract specifying supported Python/OS/architecture wheels, proxy/offline behavior, checksums, repair, upgrade, and uninstall. Where persistent package installation is unavailable (including constrained claude.ai execution environments), show OpenCV as unsupported for that surface and continue with standard scoring regardless of which installer variant is active. Keep optional runtime environments outside evidence-cache purge roots whenever they exist.

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
- silence, speech, missing audio, and missing captions;
- **(new)** generic, non-lexically-anchored bug-diagnosis cases — a screen recording where something breaks with no on-screen text or spoken cue naming the failure (the highest-stakes real use case per the README's "diagnose a bug from a video" example, and the one case class where a wrong-but-confident answer is worst). These must carry a mandatory manifest `reason` field on their gold evidence spans, since there is no lexical signal to anchor a reason to automatically.

Every case must have exact gold timestamps, required frames or intervals, and expected duplicate groups. The **manifest `reason` field is mandatory on every Tier 1 case going forward**, not only the new bug-diagnosis class, so the zero-false-drop gate (Acceptance gates) has a documented reason to audit against for every required case.

### Tier 2: curated real-world cases

Create a manifest of redistributable or URL-addressed videos covering:

- lectures and slide decks;
- screen-recorded bug reproductions;
- talking-head and podcast video;
- high-motion footage;
- tutorials with important visible text;
- long videos with **Targeted questions**;
- multilingual and caption-less sources;
- **(new)** hype/padding-exclusion cases — launch or update videos with a mix of substantive announcements and filler ("game-changer," extended cold opens, repeated calls to subscribe), gold-labeled by interval as substance vs. padding. This is the corpus support for the new hype-exclusion precision metric (Measurements) and directly targets the README's "cut the hype out of an update video" use case, which no existing recall-shaped metric can regress-detect.

Explicitly include or declare unsupported sound-event questions. Current English-caption acquisition must not silently define multilingual scope; language selection and fallback behavior are benchmark inputs.

Pin source identity, duration, checksum when downloaded, license, and gold evidence spans. Keep network end-to-end results separate from predownloaded media results. Add a **last-verified-date** and **license-status** field to every Tier 2 entry; Tier 2 stays intentionally small and vendored/self-hosted where possible so this metadata stays cheap to keep current, since nothing in this plan requires it to grow large.

**Dev/confirmatory split (new):** partition Tier 2 into a **development slice**, reusable at every milestone-boundary full gate, and an **untouched confirmatory slice**, spent exactly once, at the final confirmatory gate closing Milestone D. Milestone consolidation alone reduces how often held-out data gets peeked at; it does not zero out the multiplicity problem unless the slice spent at the final release decision was never used to tune or select anything beforehand. Freeze which items belong to which slice, and their class weighting and gold annotations, before any milestone-boundary gate runs. Tier 3 sits outside the slice system entirely: its one-time pre-claim run (below) must use items never seen at any gate.

Freeze Tier 2/3 item selection, class weighting, gold annotations, and primary metrics before tuning thresholds. Tier 1 is diagnostic and may target known risks; never present Tier 1 alone as evidence of general superiority.

### Tier 3: public video-QA subsets (deferred out of the gating loop)

**Revised.** Tier 3 licensing, pinning, and dataset-engineering work is proportionate to a "beats published baselines" claim, which nothing in the non-negotiable product requirements demands. Tier 1 plus a modest Tier 2 already answers the actual per-milestone question ("did this regress known behavior"). Defer Tier 3 entirely out of the milestone-boundary and final gating loop; run it exactly once, later, only immediately before any public comparative claim against published baselines. When it does run: use stable, license-compatible subsets of long-video and temporal-QA benchmarks, record dataset version and item IDs via pinned revisions (see Research foundations), and do not tune thresholds on the final test split.

### Question classes

Every tier should cover:

- transcript-only;
- visual-only;
- cross-modal;
- exact timestamp;
- temporal order or before/after;
- targeted long-video retrieval;
- coverage summary;
- unanswerable or insufficient-evidence questions;
- hype/padding-exclusion (Tier 2, new — see above).

## Measurements

### Evidence quality

- Evidence-span Recall@budget against gold intervals.
- Temporal intersection-over-union for localized answers.
- Recall of required before/after frame pairs.
- Duplicate-group compression and false-drop rate.
- Coverage across timeline quantiles for coverage questions.
- **(new)** Precision/over-inclusion on the hype-exclusion case class — reported, not gated, until baseline data exists to set a sane threshold (annotation is acknowledged to be more subjective than the recall-shaped metrics above; tighten annotation guidance before ever converting this to a blocking gate).

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
- **(new)** Full reader-input-token *distribution* per question class (not median alone), reported at every full-gate checkpoint from the first milestone gate onward. The architecture's own uncertainty-expansion mechanism (Candidate selection algorithm step 6) is designed to spend more on hard questions, so a median-only gate is structurally blind to exactly the tail it should be watching. p95 is data already collected for the median; promoting it from reported to a **hard blocking gate happens only at the final confirmatory gate** (end of Milestone D), once real distribution data exists to set a threshold that doesn't fight the expansion mechanism's designed behavior.
- **(new)** A "cheapest control mode a competent user would already pick" comparison column alongside every token/latency comparison, using the control's existing `transcript` / `efficient` / `--start` / `--end` paths as the baseline for each question class rather than only the control's balanced default. A headline win against the wrong baseline (e.g., beating `balanced` on a summarize request a competent user would have run as `transcript`) is not a real win.

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

### Two comparison layers, both binding

Run both layers because neither alone is fair or complete:

1. **Pipeline comparison** — convert the native control Markdown report into the versioned canonical **Evidence manifest** without dropping, summarizing, resizing, or reordering any control evidence. Feed control and candidate manifests to one frozen reader prompt. This isolates acquisition/selection/rendering quality from skill-instruction changes.
2. **Product comparison** — invoke each native `SKILL.md` through the same pinned host and reader harness. Capture every instruction or script read, tool result, image, retry, and usage record. Follow each skill contract literally, including the control instruction to review scripts, and report alternate observed-host behavior only as a separate sensitivity analysis.

**(New, closing a cherry-picking gap):** both layers are binding at every full-gate checkpoint, not just informative — a release decision may not rely on whichever layer looks more favorable per metric. Report both side by side at every milestone-boundary and final gate. This was affordable to state unconditionally only once full gates became rare (see Implementation sequence); doubling the confirmatory burden of a 15-phase schedule would have been real, doubling it four times is not.

The control adapter may normalize representation but must never improve control selection. Golden cases assert lossless control conversion.

### Grader-instrument validation (new, one-time, before the final confirmatory run)

The entire non-inferiority claim rests on the blinded semantic grader (Measurements > Answer quality), and that instrument is currently unvalidated. Before the final confirmatory run (end of Milestone D):

- Measure the grader's own measurement error (a standard error / repeatability check across repeated grading of the same answers) so a reported non-inferiority margin can be interpreted against a known instrument, not an unmeasured one.
- Check for a blinding leak: citation style, manifest formatting, or other structural tells that could let a grader infer pipeline identity despite nominal blinding. Normalize representation (citation style, manifest format) before grading if a leak is found; when normalizing, keep a written note of what was stripped so a legitimate quality signal is not silently discarded along with the tell.

This is a one-time sub-study, not a recurring per-milestone cost.

### Execution

1. Create isolated worktrees for control `83da59f` and the candidate commit.
2. Run both from clean environments against identical case manifests and **Evidence budgets**.
3. Pin FFmpeg, yt-dlp, Python, OS/architecture, host version, reader model version, prompts, temperature, evaluator rubric, and provider accounting profile. **(New)** Tag every full-gate run with a **reader-model epoch** (e.g., `reader-epoch-2026-07`); always measure control and candidate together within one epoch and never mix epochs in a single comparison. When the hosted reader model rotates, re-baseline only the *current* milestone's full gate under the new epoch, not every prior milestone's results — this prevents a silent, invalid comparison after a provider-side deprecation without requiring a second, permanently-maintained local inference stack as a hedge (rejected in the Adversarial review summary above; the hedge's own proposer doubted it would correlate with the hosted grader's judgment, which is not worth building for a solo maintainer).
4. Predownload media for core pipeline measurements; run a separate randomized network suite with retries and failure reporting.
5. Randomize control/candidate order and blind answer graders to pipeline identity.
6. Distinguish three warm states:
   - cold run with no local or reader cache;
   - same-task follow-up where control evidence may already remain in reader context;
   - new-task warm local cache where neither pipeline gets free reader context.
7. Report per-class and duration-bucket results, not only an overall mean. A gain on transcript QA must not hide a regression on UI changes or motion.
8. Publish raw JSONL case results, environment metadata, summary tables, adapter logs, and the exact comparison command.

### Statistical design and tiered gating (the load-bearing change)

Full statistical machinery applies only at milestone-boundary full gates and the final confirmatory gate (four checkpoints total across the whole project: end of Milestone A, B, C, and D — D's full gate is also the final confirmatory gate and the same checkpoint as old v1 "Phase 14"; this document uses **final confirmatory gate** for that checkpoint from here on). Every individual commit inside a milestone instead runs a **cheap, deterministic Tier-1 parity check**: does the fixed known-case set get worse, yes or no. No statistics, no confidence intervals, no held-out data — a regression fails the commit; a pass moves on. This is what makes every item below affordable to keep rather than cut.

At each full-gate checkpoint:

- Run a preregistered pilot (first occurrence only, at the Milestone A full gate) to estimate paired variance before fixing final non-inferiority sample sizes; reuse that estimate at later checkpoints unless case-mix changes materially.
- Use the video or correlated video-question group as the independent resampling unit, never individual repeated model runs.
- Stratify the paired bootstrap by question class and duration bucket; use 95% confidence intervals.
- Treat answer quality, evidence-span recall, total reader input, p95 latency, and completion rate as primary endpoints. Apply Holm correction to families of secondary comparisons.
- State the minimum detectable effect and powered sample count for each primary endpoint. Repeated model runs, at least three when available, estimate within-case variance but do not replace independent videos.
- Target a 2-percentage-point overall quality non-inferiority margin. Use a wider per-class safety margin only when the powered pilot requires it, preregister it before held-out evaluation, and report that limitation prominently.
- Draw only from the **development slice** of Tier 2 (Benchmark corpus). The **confirmatory slice** is reserved for the final confirmatory gate only.
- Never report only the best run or change thresholds after viewing held-out results.

**Per-class safety rule (two-tier, new):** a per-class point estimate worse by more than 5 points is a blocking safety signal, but the CI-bound version of this rule (block whenever the confidence interval cannot exclude a regression) applies **only at the final confirmatory gate**, paired with a stated minimum-cases stopping rule: strata with fewer than **20 cases in a class-duration bucket** at the final confirmatory gate are excluded from the blocking rule and instead reported as underpowered with mandatory disclosure — never silently averaged into an aggregate. At intermediate milestone-boundary gates, an underpowered or regressed stratum falls back to this plan's general experimental/revise/delete/disclose escape hatch rather than blocking the milestone outright. This two-tier design is what prevents both failure modes at once: a real regression cannot silently clear the final release gate, but no intermediate milestone stalls indefinitely over an underpowered stratum. (The 20-case figure is a starting policy target, not a measured constant — revise it once the Milestone A pilot's power analysis gives real variance data.)

**Fixed per-class margin (downgraded to soft recommendation):** preregistering per-class margins before any held-out run, rather than adjusting them after a pilot, was proposed as a required change. On inspection, this plan's existing safeguards — preregister-before-held-out, prominent disclosure of any widened margin — already block the worst failure mode (silent post-hoc widening). Making per-class margins fully fixed upfront risks making some question classes permanently unshippable within a realistic corpus size, for a comparatively small incremental guarantee over what already exists. Treat it as optional: adopt only if a specific class's pilot data shows a pattern of margin-gaming risk.

**Dollar ceiling (new, small addendum):** target a starting ceiling of roughly **$150 per full-gate checkpoint** (reader-model API calls plus hosted grading) and **$600 total across all four checkpoints**, revised once the Milestone A pilot gives real cost data. This is mostly a side effect of milestone consolidation — four full-cost runs instead of fifteen-plus — stated explicitly because naming a number costs nothing extra and gives an early warning if corpus size or grading cost drifts.

## Acceptance gates

Targets are design goals, not current claims. Gates below apply at milestone-boundary and final-confirmatory-gate checkpoints unless marked as a per-commit check.

### Per-commit (every commit inside a milestone)

- The deterministic Tier-1 parity suite does not regress the fixed known-case set. No statistics required; a yes/no check.

### Quality and reliability (full-gate checkpoints)

- Candidate answer accuracy and evidence-span recall meet the preregistered, pilot-powered non-inferiority margins; the design target is 2 percentage points overall.
- Per-class point estimates worse by more than 5 points are blocking safety signals even when a class is underpowered, **at the final confirmatory gate**; at intermediate milestone gates this falls back to the general experimental/revise/delete/disclose escape hatch (see Statistical design).
- Timestamp accuracy meets its preregistered absolute-error and temporal-IoU margins.
- Required local-change and before/after cases have zero known false drops in the deterministic tier, including the new generic non-lexically-anchored bug-diagnosis class.
- Completion rate is at least the control rate in every supported environment.
- Both the pipeline-comparison and product-comparison layers must independently clear every quality gate; neither may be cited alone to justify a release decision (see Experimental protocol).

### Token savings (full-gate checkpoints)

- At least 50% median total reader-input reduction on targeted questions.
- At least 25% median reduction on coverage questions without reducing timeline coverage or answer quality.
- No question class may increase median reader input without a measured quality gain that is reported explicitly.
- Every token/latency comparison also reports the cheapest-control-mode-per-class column (see Measurements); a win must hold against that baseline, not only the control's balanced default.
- Full reader-input-token distribution is reported per class at every full-gate checkpoint; p95 becomes a hard blocking gate only at the **final confirmatory gate**.
- Hype-exclusion precision is reported, not gated, at every full-gate checkpoint until enough data exists to set a threshold.

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

**Revised — this is the plan's single biggest structural change.** v1's 15 phases (Phase 0-14, plus 12 lettered sub-phases) collapse into **4 milestones**, matching the plan's own hypothesis groupings. Each milestone lands as however many commits it takes, each gated only by the cheap deterministic Tier-1 parity check (Acceptance gates > Per-commit). One full statistical confirmatory run (Experimental protocol's tiered gating) closes each milestone. The Milestone D full gate is also the **final confirmatory gate** referenced throughout this document (equivalent to v1's "Phase 14").

### Milestone A — shrink the skill interface, add question-aware retrieval

Corresponds to v1 old Phase 0-4. Work items, in order:

- Freeze case, gold-annotation, **Evidence budget**, and result schemas (old 0A).
- Implement the lossless control-to-manifest adapter and golden parity tests (old 0B).
- Implement the two-layer worktree/host runner and total-cost instrumentation (old 0C).
- Add generated recipes, curated manifests, and failure-injection cases (old 0D).
- Build the pilot and power-analysis machinery and the preregistered statistical-report format (old 0E); the fresh pilot itself — the only one in the plan — runs as part of Milestone A's closing full gate below, and its variance estimates are reused at later checkpoints.
- Add the versioned **Evidence manifest** with control-equivalent candidate output before changing selected evidence; preserve setup remediation, errors, cleanup guidance, path resolution, and silent repeat preflight; validate copied, symlinked, and bundled layouts (old Phase 1).
- Move deterministic orchestration behind the Evidence compiler module; remove first-use script-review requirements only after release and behavior tests cover them; measure prompt savings separately from evidence changes (old Phase 2 — H1).
- Pass the complete **Question** and explicit/automatic policy into the evidence compiler; preserve control evidence until retrieval lands; test ambiguity, multipart requests, user override, and conservative fallback (old Phase 3).
- Canonicalize and test VTT/Whisper segments; add dependency-free lexical retrieval and selected transcript windows; preserve complete transcript evidence for **Coverage questions** (old Phase 4 — H2).

**Milestone A full gate:** full statistical protocol (Experimental protocol), drawing on the Tier 2 development slice.

### Milestone B — acquisition, transcription, extraction efficiency, minimal evidence store

Corresponds to v1 old Phase 5-8, 10. Work items, in order:

- Extract/transcribe requested audio ranges before upload or local inference; preserve absolute timestamps and partial failure behavior (old Phase 5 — H11).
- Use section download where supported and preserve full-download fallback; test long-GOP/keyframe edges, final-frame ranges, and site variance (old Phase 6 — H7).
- Plan captions, metadata, audio, and video from required modalities; eliminate repeated yt-dlp work without changing evidence (old Phase 7 — H10).
- Batch cue timestamps where benchmarks show a gain; reuse already-probed metadata and record process counts (old Phase 8 — H12).
- Build the minimal Evidence store module: content-addressed cache keys, no locking/purge/corruption-handling in this first version, and the `--no-cache` flag; update user-facing persistence/privacy documentation before enabling it; benchmark cold, same-task follow-up, and new-task warm states fairly (old Phase 10 — H6, now including H6's amortization caveat as a measured question, not an assumption).

**Milestone B full gate:** full statistical protocol, drawing on the Tier 2 development slice.

### Milestone C — scout separation, coarse-to-fine selection, adaptive resolution

Corresponds to v1 old Phase 9, 11-12. Work items, in order:

- Add multi-scale local-change fixtures and raw scout measurements (old 9A — H3).
- Compare one-pass full-resolution and two-stage low-resolution adapters (old 9B).
- Compare standard, FFmpeg-native, and OpenCV scorers — this ablation now precedes and gates any installer investment (old 9C — H8; see OpenCV decision). H8's required evidence is this ablation, so it belongs in Milestone C by evidence location; H9 (optional OCR/embeddings adapters, old Phase 13) belongs in Milestone D on the same basis. The same v1 Phase 13 bullet also carries local-ASR evaluation; ASR has no assigned hypothesis ID (see Implementation repository review's faster-whisper/whisper.cpp/WhisperX candidates) and is scoped to Milestone D as an unhypothesized optional adapter, not as part of H9. The consolidation synthesis's own C/D hypothesis labels conflated H-numbers with old phase-numbers ("H13-H14" does not exist in the Hypotheses table); this document resolves the mapping by where each hypothesis's required evidence is actually produced.
- Add temporal clustering, cue/detail collision handling, and required neighbor pairs (old 9D).
- Add relevance-plus-coverage selection with control fallback (old 11A — H4); Coverage questions still receive relevance spending after their hierarchical anchors, per the Candidate selection algorithm's step 3.
- Add hierarchical refinement as a separate ablation, gated to **Targeted questions** per the DIG finding (old 11B).
- Add adaptive diversity and uncertainty expansion as separate ablations; preserve uniform anchors for **Coverage questions** throughout (old 11C).
- Account for context cost before materialization; add source-linked crop provenance and readability/exactness tests (old Phase 12 — H5).
- Evaluate the H6 amortization caveat and, if the ablation confirms it is needed, build a narrow, on-demand Scout short-circuit for clearly localized questions rather than running Scout unconditionally (the H6-caveat evaluation noted under the Hypotheses table, run alongside this milestone's H4 ablations and reusing the focused-range machinery H7 lands in Milestone B).

**Milestone C full gate:** full statistical protocol, drawing on the Tier 2 development slice. Offer the installer choice (documented `WATCH_VISION_BACKEND` opt-in, or the fuller installer if earned) only after this gate states real tradeoffs.

### Milestone D — optional adapters, distribution identity, final confirmatory gate

Corresponds to v1 old Phase 13-14. Work items, in order:

- Evaluate OCR and semantic embeddings as optional adapters (H9), and local ASR as a separate optional adapter with no assigned hypothesis ID; keep all optional runtimes isolated from the base interpreter and default bundle.
- Update derivative manifests, marketplace metadata, repository links, and exact install/update commands while preserving upstream attribution.
- Automate version synchronization, exactly-one-SKILL artifact structure, executable scripts, copied/symlinked layouts, and update-from-prior-version tests.
- Run the grader-instrument validation sub-study (Experimental protocol) once, before spending the confirmatory slice.
- Run Tier 3 once, if a public "beats published baselines" claim is intended (Benchmark corpus); otherwise skip it.
- Run the held-out suite against the **confirmatory slice**, apply the two-tier per-class safety rule at full CI-bound strength, and ask an independent agent to reproduce from a fresh clone.
- Publish limitations and per-class results; change the default only after every gate passes.

**Milestone D full gate = the final confirmatory gate.** This is the only checkpoint that spends the confirmatory slice, applies the CI-bound per-class blocking rule at full strength, promotes p95 token tail to a hard gate, and authorizes a public claim under Evidence required for a public claim (below).

## Installation smoke-test matrix

These are Milestone D target commands; current manifests still identify the upstream control and must not be presented as derivative release metadata until that milestone's work completes. Test from a clean environment:

| Surface | Install | Update or rebuild | Required assertion |
| --- | --- | --- | --- |
| Claude Code | `/plugin marketplace add abe238/claude-video-plus`, then `/plugin install watch@claude-video-plus` | `/plugin update watch@claude-video-plus` | derivative identity and upstream attribution are both clear; `/watch` resolves self-contained scripts |
| Agent Skills hosts | `npx skills add abe238/claude-video-plus -g` | `npx skills update watch -g` | discovered skill includes all runtime files |
| Targeted Agent Skills host | `npx skills add abe238/claude-video-plus -a codex` | `npx skills update watch -a codex` | host-specific install path works |
| claude.ai artifact | download the derivative release `watch.skill` | `bash skills/watch/scripts/build-skill.sh` | archive root and executable scripts are valid |
| Manual development | clone `abe238/claude-video-plus` + symlink `skills/watch` | `git pull` | relative script resolution survives symlink |
| Optional OpenCV | set `WATCH_VISION_BACKEND=opencv` and run the documented install command | change the env var to switch backend, or repair per documentation | default (`stdlib`) keeps baseline working with no setup change; failure falls back deterministically |

Initial declared base matrix: current supported Python versions on macOS arm64/x86_64, Ubuntu x86_64, and Windows x86_64, with FFmpeg/ffprobe and yt-dlp available as documented. Test representative Claude Code, Codex, Cursor, and manual layouts; validate the Agent Skills artifact contract for other hosts rather than claiming direct execution on all 50+. Expand the matrix only when CI or a recorded manual run exists.

Offline deterministic layout/preflight tests must pass 100%. Run marketplace, private/public GitHub access, package-manager, and update tests separately because they depend on external services; record attempts, retries, and confidence. Optional adapters must not change default install success.

## Review instructions for another agent

The reviewer should:

1. Verify `83da59f` is the untouched upstream ancestor and suitable control.
2. Inspect whether every claimed metric can be collected without favoring the candidate.
3. Challenge the corpus for missing video/question classes and leakage.
4. Check that non-inferiority and confidence rules prevent cherry-picking.
5. Verify installation and failure-injection gates are first-class, not afterthoughts.
6. Identify any milestone work item that changes behavior before the per-commit parity check or a full gate can measure it.
7. Recommend deletions where a proposed dependency or module lacks measurable leverage.
8. Confirm the development slice and confirmatory slice of Tier 2 have not been mixed — the confirmatory slice must show zero use before the final confirmatory gate.
9. Return blocking concerns separately from optional improvements.

The first independent review of v1 found blockers in comparison fairness, budget accounting, statistical power, phase attribution, and optional installation. After revision, the second review returned no blockers and a **READY for Phase 0** verdict. A subsequent five-lens adversarial review (this document) found v1's phase/gating/module structure itself to be the primary remaining risk — not a blocker to any single measurement, but a structural one threatening the whole schedule's affordability — and produced this revision. This does not authorize optimization or superiority claims before the Milestone A full gate passes.

## Contribution workflow

Unchanged from v1; no adversarial finding targeted this section.

Current owner-directed work may be committed directly to `main` at coherent, tested checkpoints. If another person contributes in the future, use a branch and pull request so benchmark evidence, attribution, implementation, and review remain inspectable.

## Evidence required for a public claim

Two artifacts below are new relative to v1: the confirmatory-slice item list and the reader-model epoch tag.

Any README or release claim that the candidate is better must link to:

- control and candidate commit hashes;
- corpus manifest and dataset versions, including which Tier 2 items belonged to the confirmatory slice (plus Tier 3 dataset versions and item IDs if a beats-baselines claim is made);
- the reader-model epoch tag used for the final confirmatory gate;
- environment lock information;
- exact reproduction command;
- raw paired results;
- summary with confidence intervals;
- known regressions, exclusions, and failed cases.

Until those artifacts exist, describe all expected improvements as hypotheses.