# 2026-07 cross-fork bake-off — preregistered protocol (M1)

Status: **FROZEN AT COMMIT TIME.** The commit that introduces this file is the
preregistration timestamp. Nothing below may change after that commit except via
the amendment rule in §10. No comparative run (M3) may start before this file is
committed; git history proves the order.

Scope: comparative evaluation of four claude-video forks on captioned YouTube
videos under **default-user behavior** (documented defaults only). Source plan:
`docs/plans/COMPETITIVE-PLAN-2026-07.md` Track M; loop `L5` of
`docs/LOOP_CHAIN_2026-07-18.md`. Measurement conventions inherit from
`docs/execution/v1/MEASUREMENT.md`; where this protocol is silent, MEASUREMENT.md
governs.

Estimand: answer accuracy against frozen keys, on captioned videos, with cloud
transcription disabled in every arm. **Transcription (ASR) variance is excluded
from the primary estimand**, deliberately and openly: all corpus videos have
YouTube captions and every arm consumes captions. A separate exploratory
transcription track may follow; it is out of scope here and nothing in this
document supports transcription claims.

## 1. Corpus

9 captioned YouTube videos across four categories. The three L5 calibration
videos (validated end-to-end in `docs/evidence/L1-audit/`) are included. All
others were verified captioned via `yt-dlp --list-subs` on 2026-07-18.

| # | Video ID | URL | Category | Duration | Channel | Expected caption track |
|---|---|---|---|---|---|---|
| C1 | `QacqRZ0vsD4` | https://www.youtube.com/watch?v=QacqRZ0vsD4 | talk | 43:28 | The Next New Thing | `en` (auto) |
| C2 | `ZW6d_2rwcdk` | https://www.youtube.com/watch?v=ZW6d_2rwcdk | screencast | 22:32 | Leon van Zyl | `en` (manual) |
| C3 | `zQnBQ4tB3ZA` | https://www.youtube.com/watch?v=zQnBQ4tB3ZA | fast-cut | 2:25 | Fireship | `en` (auto) |
| C4 | `zjkBMFhNj_g` | https://www.youtube.com/watch?v=zjkBMFhNj_g | talk | 59:48 | Andrej Karpathy | `en` (auto) |
| C5 | `iG9CE55wbtY` | https://www.youtube.com/watch?v=iG9CE55wbtY | talk | 20:03 | TED | `en` (manual) |
| C6 | `ZDa-Z5JzLYM` | https://www.youtube.com/watch?v=ZDa-Z5JzLYM | screencast | 15:24 | Corey Schafer | `en` (manual) |
| C7 | `rBpaUICxEhk` | https://www.youtube.com/watch?v=rBpaUICxEhk | fast-cut | 4:01 | After Skool | `en` (manual) |
| C8 | `dQw4w9WgXcQ` | https://www.youtube.com/watch?v=dQw4w9WgXcQ | music | 3:33 | Rick Astley | `en` (manual) |
| C9 | `9bZkp7q19f0` | https://www.youtube.com/watch?v=9bZkp7q19f0 | music | 4:12 | officialpsy | `en` (auto; original audio Korean) |

C1–C3 are the calibration videos; the remainder are from stable, popular
channels (TED, Karpathy, Corey Schafer, Fireship, After Skool, official artist
channels) chosen to minimize takedown/re-edit risk.

Caption freeze: at freeze time the expected caption track for each video is
downloaded once and its SHA-256 recorded in `FREEZE.json` (see §11). At run
time, each arm's consumed caption is hashed and compared; a mismatch marks the
case `caption_drift` (handled per §8). C9 is a deliberate non-English-audio
stress case; because auto-translated captions are the least stable track type,
C9 is the first candidate to drop under §8 rule F2, and the corpus stays at or
above the minimum family count (§7) without it only if no other family drops.

## 2. Question families and dependency structure

Question families (strata): **targeted** (a specific fact stated at one point in
the video), **summary** (whole-video synthesis), **visual** (answerable only
from what is on screen, not from the transcript), **numeric** (an exact number,
count, or timestamp).

Allocation: 16 questions total, ≥2 per family corpus-wide (actual: 4 per
family), spread so that no video carries more than 3 questions.

| Video | targeted | summary | visual | numeric | total |
|---|---|---|---|---|---|
| C1 | 1 | 1 | — | — | 2 |
| C2 | 1 | — | — | 1 | 2 |
| C3 | — | 1 | 1 | — | 2 |
| C4 | 1 | 1 | — | 1 | 3 |
| C5 | 1 | — | — | 1 | 2 |
| C6 | — | 1 | 1 | — | 2 |
| C7 | — | — | 1 | — | 1 |
| C8 | — | — | 1 | 1 | 2 |
| Total | 4 | 4 | 4 | 4 | 16 |

C9 carries no scored question; it is a caption-robustness canary: every arm runs
it, completion and wall time are reported, but it contributes no accuracy rows
(auto-translated captions make a fair frozen key impossible).

**Dependency families.** All questions on the same video form one dependency
family (MEASUREMENT.md "source family"). With 8 question-bearing videos there
are **8 families**. Families, not cases, are the resampling unit (§7).

**Question and answer-key procedure (frozen order of operations):**

1. Before any pipeline runs, the protocol author watches each video (human
   viewing, no arm's tooling) and writes the final question text plus one
   answer key per question. Keys state the required facts, acceptable
   paraphrase bounds, and for numeric questions the exact value and tolerance.
2. Question text is committed in plain text as `QUESTIONS.md` in the freeze
   commit.
3. Answer keys are committed **hashed**: `ANSWER-KEYS.sha256` in the freeze
   commit contains the SHA-256 of the canonical `answer-keys.json` (UTF-8,
   sorted keys, `\n` line endings). The plaintext file is withheld from the
   repo until results publication, then published verbatim alongside results;
   its hash must match the frozen value.
4. Keys are never edited after freeze. A key found defective mid-run retires
   its case under §8 rule F4 (disclosed); it is not silently rewritten.

## 3. Arms

| Arm | Repo | Pinned commit | Notes |
|---|---|---|---|
| `ours` | `abe238/claude-video-plus` | `cc57e0986b2eba58045a3c20d71969623af81d1e` (tag `v1.2.0`) | frame-engine v2 default + transcript-correctness release |
| `upstream` | `bradautomates/claude-video` | `83da59fa78c3eee9e20f515fe75c438bb5166efd` | the repo's frozen control |
| `real-video` | `HUANGCHIHHUNGLeo/claude-real-video` | `6f6c25fa9cd7a1b9bac2dbbd526a8a4f6f42cfbb` (master @ 2026-07-18) | |
| `video-vision` | `jordanrendric/claude-video-vision` | `5c8bc7ba32b727c7f97e9a7b336a775e0c6cd911` (main @ 2026-07-18) | |

Rules:

- **Documented defaults only.** Each arm is invoked exactly as its own README /
  SKILL.md documents for "answer a question about this video", with no flags
  beyond what its docs present as the default question-answering invocation.
  One uniform exception, preregistered here: cloud transcription is disabled in
  every arm (captions-only estimand, §0); the arm's documented off-switch is
  used and disclosed. If an arm has no off-switch, its cloud path is disabled
  by withholding API keys from its environment, and this is disclosed.
- **Per-arm command lines disclosed verbatim.** The exact argv for every
  (arm, case) execution is recorded in that case's run receipt and reproduced
  verbatim in the published results. The canonical per-arm invocation template
  is frozen in `RUNNERS.md` at M2, before M3, and hashed into `FREEZE.json`.
- **Competitor-suggested configurations** are welcome as *additional, labeled*
  rows (e.g. `real-video (author-tuned)`) via PR against this repo. They never
  replace or reflow the default rows, and they rerun under this same protocol.
- Runner environments pin tool paths, versions, and content SHA-256s for
  python / ffmpeg / ffprobe / yt-dlp following the conventions of
  `tools/control_harness.py` (isolated HOME, allowlisted env, empty external
  output dirs, receipts with raw stdout/stderr and output manifests).

## 4. Execution

- Case ID: `bakeoff-<video#>-<family>-<q#>` (e.g. `bakeoff-C4-numeric-1`).
- **Arm order per case** is deterministic from the case ID, generalizing
  `tools/control_harness.py::paired_order` (which is 2-arm) to 4 arms:
  `order = permutations(sorted(arm_ids))[int.from_bytes(sha256(case_id)[:4], 'big') % 24]`.
  This is frozen here; the 2-arm `paired_order` function remains the rule for
  ours-vs-control gate runs elsewhere in the repo.
- All four arms of a case run on the same machine, same day, same pinned tool
  set, same network policy, with the source bytes/captions fetched per-arm but
  hash-verified against the frozen caption hash.
- One invocation per arm per case, plus at most one retry per §8.
- Wall time is measured process start → exit for the arm's documented
  invocation, including its downloads; recorded per attempt.

## 5. Judging

- **≥2 judges from distinct model families** (one Anthropic Claude model, one
  OpenAI GPT model). Exact model IDs are pinned in `FREEZE.json` at freeze time
  and never substituted mid-run; a provider deprecation mid-run is an
  instrument failure, disclosed, and the affected cases are re-judged by both
  judges under an amended freeze entry.
- **Blinding.** Judges see: question, plaintext answer key, and the candidate
  answers labeled with opaque per-case arm labels. Judges never see fork names,
  configs, token counts, wall times, or costs. Opaque label:
  `sha256(case_id + ":" + arm_name + ":" + SALT).hexdigest()[:6]` with a salt
  generated at freeze time, stored outside the repo, and published with the
  results (making the blinding auditable after the fact).
- Judges score each (case, arm) answer **independently** (one answer per call;
  no side-by-side ranking, which leaks arm count and invites position bias).
- **Scoring rubric** (inherited from MEASUREMENT.md, frozen): four integers
  0–10 — correctness, completeness, citation/timestamp support, adherence.
  Per-judge score = `0.40*correctness + 0.25*completeness + 0.25*citation +
  0.10*adherence`. Case/arm accuracy = arithmetic mean over valid judges. One
  judge refusal → one same-protocol replacement attempt; fewer than two valid
  judges invalidates that case's quality result for **all** arms (never
  selectively).
- **Frozen judge prompt (verbatim; both judges; the only variable parts are the
  three bracketed slots):**

```text
You are grading one answer to one question about a video.

QUESTION:
[question text]

ANSWER KEY (authoritative; grade strictly against it, not outside knowledge):
[answer key text]

CANDIDATE ANSWER (label: [opaque label]):
[answer text]

Score four integers from 0 to 10:
- correctness: claims match the answer key; unsupported or contradicted
  claims lose points.
- completeness: covers every element the answer key marks as required.
- citation: claims are supported by timestamps or on-screen references
  consistent with the answer key.
- adherence: follows the question's instructions (format, scope, units).

Numeric questions: the key states the exact value and tolerance; a value
outside tolerance caps correctness at 2.

Respond with JSON only:
{"correctness": N, "completeness": N, "citation": N, "adherence": N}
```

## 6. Metrics

- **Primary: answer accuracy vs frozen key**, reported per family and per
  question-family stratum (targeted / summary / visual / numeric). This is the
  only metric that can support a comparative claim.
- **Secondary: tokens delivered to the reader** — the volume of report text +
  images each arm hands the answering model. Provider-reported token usage and
  estimated tokens (chars/4 or a named tokenizer) are **separate columns and
  never mixed**; a table cell is labeled `reported` or `estimated`.
- **Secondary: wall time** per (arm, case), median and p95 per arm.
  **Reported win or lose** — publication of the wall-time table is
  unconditional.
- All secondary metrics are descriptive context; no gate converts a token or
  latency win into a quality claim.

## 7. Statistical treatment

- Unit of analysis: dependency family (§2). Per-family accuracy = arithmetic
  mean of its cases' accuracy scores per arm; every family weighs equally.
- Pairwise arm contrasts use the repo's **deterministic 10,000-resample
  family-clustered bootstrap** (MEASUREMENT.md "Confirmatory quality gate"):
  sample F families with replacement from the F observed families, average
  family-mean paired deltas, sort replicates, one-sided 95% bound at
  nearest-rank `ceil(0.05*10000)-1` (zero-based). Seed frozen in `FREEZE.json`.
- **Preregistered minimum family count: 8.** Justification: the corpus yields
  exactly 8 question-bearing families (§2); 8 is the smallest F for which the
  family bootstrap resamples from a support of 8^8 ≈ 1.7e7 distinct draws,
  comfortably above the 10,000 replicates, and any loss of a family (caption
  takedown, key retirement) drops F below the design size — at which point the
  run no longer matches its own preregistration. Therefore: **if fewer than 8
  families survive to analysis, all results are labeled DESCRIPTIVE ONLY and no
  superiority claims are made by anyone, for any arm, in any direction.**
- Per-stratum (targeted/summary/visual/numeric) tables are always reported but,
  at 2–4 families per stratum, are **always descriptive**; no stratum-level
  superiority claims under this protocol.

## 8. Failure and exclusion rules (mechanical, preregistered)

- **F1 — arm errors on a case** (nonzero exit, timeout, empty required output):
  retry once, same invocation. Second failure → the case row remains, scored
  as failure for that arm (accuracy 0, completion "failed"), disclosed in the
  results with the raw error class. Failed-attempt wall time is included in
  that arm's cost columns (MEASUREMENT.md).
- **F2 — captions disappear or drift** (video deleted, made private, caption
  hash mismatch vs freeze): the case is **dropped for all arms**, disclosed
  with the observed vs frozen hash. Dropping a video drops its whole family;
  see §7 min-N consequence.
- **F3 — a runner cannot install** at its pinned SHA on the run environment
  after a documented, good-faith attempt: the arm is marked **NOT-RUN** with
  the reason (commands attempted, error output) published; its rows show
  NOT-RUN, never 0. NOT-RUN arms appear in every published table.
- **F4 — defective answer key** discovered mid-run (ambiguous, wrong, or
  unanswerable from the video): case retired for all arms, disclosed with the
  defect description. Keys are never edited post-freeze.
- **F5 — judge infrastructure failure** after the replacement attempt: quality
  invalid for that case (all arms), reported as instrumentation failure; never
  converted into a win for any arm.
- No other exclusions exist. Any exclusion not on this list retires the case
  from claims and is reported (MEASUREMENT.md outcome-aware exclusion rule).

## 9. Logs

- Every (arm, case, attempt) produces a receipt: argv, environment fingerprint
  (tool versions + SHA-256s), start/end UTC, exit code, raw stdout/stderr,
  output-tree manifest with per-file SHA-256 — the shape established by
  `tools/control_harness.py` receipts.
- Logs are **deterministically redacted** before publication by a committed
  script (`bench/bakeoff/redact.py`, M2): replaces the run user's home prefix
  with `~`, strips environment dumps, and removes strings matching the
  preregistered secret patterns (API-key shapes: `sk-…`, `gsk_…`, `xoxb-…`,
  AWS `AKIA…`, plus `Authorization:` headers). Deterministic: identical input
  bytes always produce identical redacted bytes.
- Published under `docs/benchmarks/2026-07-bakeoff/logs/`, with a top-level
  `SHA256SUMS` manifest over every published log file.

## 10. Publication rules

- Results are published as `docs/benchmarks/2026-07-bakeoff/RESULTS-<date>.md`
  (dated; never undated, never overwritten in place — corrections append).
- **Per-family tables are mandatory and complete**: every family × arm cell,
  including every cell where `ours` loses. Stratum tables likewise. Failures,
  NOT-RUN arms, and dropped cases appear in the tables, not footnotes.
- **No superiority language** — in results, README, landing pages, or release
  notes — for any comparison where §7's gate does not hold (min-N met AND the
  bootstrap bound clears zero for that contrast). Below min-N, the only
  permitted framing is "descriptive; no claim".
- Wall-time and token tables are published regardless of who wins (§6).
- **Correction policy for competitors:** maintainers of any measured fork may
  open a PR against this repo to (a) add an author-suggested configuration as
  a separate labeled row, (b) dispute a runner's invocation as
  non-default with a pointer to their docs, or (c) flag a scoring or data
  error. Valid disputes trigger a dated correction section in the results file
  and, where the fix changes an invocation, a rerun of the affected rows under
  this same protocol. The original rows remain visible, marked superseded.
- **Amendments to this protocol** after freeze are append-only, dated, in an
  "Amendments" section, each with a rationale; an amendment that touches the
  corpus, questions, keys, arms, judges, or statistics after any M3 data
  exists demotes the entire run to DESCRIPTIVE ONLY.

## 11. Freeze declaration

The freeze commit — the commit introducing this file together with
`QUESTIONS.md`, `ANSWER-KEYS.sha256`, and `FREEZE.json` — is the
preregistration timestamp. `FREEZE.json` pins, exactly:

1. **Corpus URLs and video IDs** — the 9 rows of §1, verbatim.
2. **Caption hashes** — SHA-256 of the downloaded expected caption track per
   video, captured at freeze time.
3. **Answer keys** — SHA-256 of canonical `answer-keys.json` (plaintext
   withheld until publication; §2).
4. **Question text** — committed in plain text (`QUESTIONS.md`) and its
   SHA-256 recorded.
5. **Judge prompts** — SHA-256 of the verbatim prompt in §5; judge model IDs
   for both model families.
6. **Runner SHAs** — the four pinned arm commits of §3; plus, at M2 (before
   any M3 run), the SHA-256 of `RUNNERS.md` (canonical invocation templates)
   and `bench/bakeoff/redact.py`.
7. **Statistics** — bootstrap seed, resample count (10,000), minimum family
   count (8).
8. **Blinding salt** — SHA-256 of the salt (salt itself withheld until
   publication).

Verification at publication: every withheld plaintext (answer keys, salt) is
published and must hash to its frozen value; any mismatch voids the run.
