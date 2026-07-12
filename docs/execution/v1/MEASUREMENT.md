# v1.0 measurement and decision specification

Freeze this file, the evaluator version, supported classes/environments, and corpus registry
before the first metric-changing packet.

## Units and pairing

- Primary quality unit: one independently labeled Video source × Question case.
- Dependence unit: source family, including reuploads, excerpts, derivatives, episodes from the
  same series, and videos sharing substantially identical source material.
- Control and Candidate use the same case, source bytes/captions, Question, explicit flags,
  Evidence budget, reader prompt/model epoch, timeout, retry policy, and grading procedure.
- Alternate arm order deterministically from the case ID hash.
- Report case rows, family-clustered aggregates, medians, p95 values, denominators, exclusions,
  and all categorized failures.

## Missing data and failures

- Timeout, crash, empty required output, grader refusal, or missing measurement remains a row;
  it is never silently excluded.
- For completion/quality gates, a Candidate-only failure receives the worst score and counts as
  incomplete. A Control-only failure remains visible and does not automatically create a win.
- For cost/latency gates, failed attempts include all work until failure. A retried successful run
  includes the failed attempts.
- Exclusions must be preregistered mechanical rules. Outcome-aware exclusions retire the case
  from claims and are reported.

## Development gates

### Frozen scoring algorithms

Each non-refused judge scores four 0–10 integers using the same rubric: factual correctness
(unsupported or contradicted claims lose points), completeness against required obligations,
citation/timestamp support, and Question-instruction adherence. The per-judge score is
`0.40*correctness + 0.25*completeness + 0.25*citation + 0.10*adherence`. A case/arm score is
the arithmetic mean across at least two valid blind judges. One refusal is discarded after one
same-protocol replacement attempt; fewer than two valid judges makes both arms' quality result
invalid for that case and triggers the frozen missing-data rule rather than selective exclusion.

A selected interval matches a gold interval when temporal IoU is at least 0.25. A gold point
event matches a selected frame within ±2.0 seconds or a selected span containing the point.
Case Evidence-span recall is matched required gold items divided by all required gold items;
case temporal IoU is the mean, over gold intervals, of the highest selected-span IoU (zero when
unmatched). A before/after obligation matches only when at least one selected item matches each
labeled window and their source timestamps preserve order. Before/after recall is matched pairs
divided by required pairs.

For quality paired deltas, a Candidate-only runtime failure scores Candidate 0 and retains the
Control score; a Control-only runtime failure scores Control 0 and retains the Candidate score;
both-arm runtime failure scores both 0 and remains in completion denominators. A grader failure
after replacement invalidates quality for both arms but remains a reported instrumentation
failure and cannot be converted into a win. Arithmetic means include all non-invalid paired
rows; completion always includes every case.

Tier 1 deterministic fixtures must all pass. On the reusable development slice, a mechanism may
remain for further evaluation only when:

- answer-quality paired mean is no worse than Control by more than 0.25 points on a 10-point
  scale overall, with no supported class worse by more than 0.50;
- Evidence-span recall is no worse by more than 0.02 absolute overall, required before/after
  recall has zero known deterministic false drops, and citation support does not regress by more
  than 0.02 absolute;
- Candidate completion is not lower than Control by more than one case or 1 percentage point,
  whichever is stricter;
- the mechanism improves at least one declared primary outcome outside the measured noise band;
- privacy, exact-name/number/timestamp/negation, install, and fallback invariants have zero known
  deterministic regressions.

Development gates choose what to test next; they do not authorize public superiority claims.

## Confirmatory quality gate

Use a family-clustered paired bootstrap with 10,000 deterministic resamples and a preregistered
seed. First compute each source family's arithmetic mean paired delta, giving every family equal
weight regardless of its number of cases. For each replicate, sample `F` families with
replacement from the `F` observed families, average their family means, and retain the result.
Sort 10,000 replicate values; the one-sided 95% lower bound is nearest-rank element
`ceil(0.05*10000)-1` with zero-based indexing. The bound must exceed:

- −0.25 answer-quality points overall and −0.50 in every supported Question class;
- −0.02 absolute Evidence-span recall overall;
- −0.02 absolute citation support overall.

Completion must be at least Control in every supported environment. Required deterministic
exactness/privacy/install gates remain absolute blockers regardless of statistical results.
The pilot determines and freezes the minimum family count before opening the confirmatory slice;
underpowered classes are disclosed and cannot support class-specific claims.

## Token and cost gates

- Reader text tokens: provider tokenizer when available; otherwise named tokenizer/version.
- Reader image tokens: provider-reported usage; estimates are labeled and never mixed with
  reported usage in a gate.
- All-model input/output, selector/embedding/reader calls, dollars, and transmitted units are
  separate columns plus a total-system column.
- Final targeted median reader-input reduction must be at least 50%; Coverage reduction at least
  25%. Quality and completion gates must pass first.

## Latency and resource gates

For each environment/state/duration bucket, run at least 30 no-op or unchanged-path repeats and
30 paired workload repeats. Define jitter allowance as the larger of 5 ms, 5% of the Control
median, or the no-op p95−p50 spread. Candidate median and p95 may not exceed Control by more than
that allowance on default behavior. Report cold and warm separately, plus CPU time, peak RSS,
disk, network bytes, process launches, and optional initialization.

For every percentile, sort finite observations ascending and select zero-based index
`ceil(p*n)-1`; require at least 20 observations for p95. Predeclared practical/noise bands are
0.10 answer-quality points, 0.01 absolute recall/citation support, 2% reader tokens/cost, and the
latency jitter allowance above. “Beyond noise” always means exceeding the applicable band.

Successful repeat preflight uses 30 warm runs on each supported Tier A environment; p95 must be
under 100 ms and output empty.

## ASR gates

- WER uses case-folded, punctuation-normalized reference text with substitutions + deletions +
  insertions divided by reference words.
- Candidate WER may not exceed the best applicable existing Adapter by more than 1.0 absolute
  percentage point overall or 2.0 in a supported language class.
- Median absolute segment-boundary error may not regress by more than 0.25 seconds; p95 may not
  regress by more than 1.0 second.
- Report real-time factor, uploaded bytes, model/version, language, and failure rate.

The comparator is frozen per case before audio is processed: Groq changes compare with the
shipped Groq Adapter, OpenAI changes with the shipped OpenAI Adapter, YAP with the shipped cloud
Adapter selected by the pre-outcome `auto` order, and a loopback faster-whisper-compatible
endpoint with YAP on supported macOS. If the preregistered comparator is unavailable, the row is
`unavailable` and cannot be reassigned after outcomes are seen.

## Pareto and removal rule

A candidate is promoted only if it improves at least one primary outcome beyond jitter or the
declared practical margin, passes every blocker, and is not strictly worse on quality,
completion, tokens/cost, latency, install reliability, privacy, and supported-platform coverage.
If two policies are indistinguishable inside all noise/margin bands, keep the simpler existing
policy. Losing signals and unreachable optional paths are deleted.

## Confirmatory sealing

The corpus registry hashes source identities and assigns whole source families to development or
confirmatory slices. The coordinator is custodian; executors receive development IDs only.
Before reserve access, freeze Candidate commit/config, routing table, prompts, reader/grader
epochs, evaluator, exclusions, supported classes/environments, and sample size. Append every
reserve access to an immutable log. If comparative outcomes are exposed before a valid verdict,
the cohort is spent; any influenced implementation uses a newly drawn sealed cohort.
