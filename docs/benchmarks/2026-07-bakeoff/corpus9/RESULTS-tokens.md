# Corpus-9 mechanical results — ours (v1.2.2) vs original (83da59f)
Keys frozen at 9debf2b BEFORE these runs (git history proves order). Same machine.
Balanced = equal frame budget both sides. Evidence engages only on videos >9min.

| Video | Type | orig tok | ours-bal | save | ours-ev | ev save | orig maxgap | ours maxgap |
|---|---|---|---|---|---|---|---|---|
| Ken Robinson TED | talk 20m | 10,759 | 8,255 | -23% | 4,203 | -61% | 846s | 41s |
| Python OOP | screencast 15m | 8,643 | 5,448 | -37% | 5,265 | -39% | 240s | 93s |
| Karpathy LLMs | talk 60m | 36,733 | 21,476 | -42% | 8,793 | -76% | 535s | 120s |
| repo roundup | talk 43m | 30,493 | 18,804 | -38% | 9,208 | -70% | 480s | 87s |
| Claude Code | screencast 22m | 15,670 | 10,677 | -32% | 1,865 | -88% | 166s | 46s |
| Alan Watts | short 4m | 3,209 | 2,992 | -7% | (n/a <9m) | | 29s | 29s |
| TypeScript 100s | short 2.4m | 2,587 | 2,161 | -16% | (n/a) | | 63s | 30s |
| Gangnam (canary) | music 4m | 5,146 | 5,159 | +0% | | | 28s | 22s |
| Rick Astley (canary) | music 3.5m | 5,163 | 5,525 | **+7% (LOSS)** | | | 9s | 9s |

## Honest read
- **Substantive videos (the actual use case): -23% to -42% tokens balanced at equal frames, -39% to -88% in evidence mode, and 2x-20x better coverage** (worst uncovered gap). The savings scale with video length and caption overlap.
- **Short videos: modest (-7% to -16%)** — less caption overlap to collapse, and evidence mode correctly doesn't engage under 9 minutes.
- **PUBLISHED LOSS: on music videos ours can be slightly LARGER** (Rick Astley +7%). No substantive transcript to dedup, and ours adds the author-description block that a music video's promo copy doesn't earn. Fixable (skip the description when it's below a signal threshold) — logged, not hidden. Gangnam is +0% (parity).
- All 22 runs rc=0. Music canaries confirm the tool handles non-substantive video without crashing.

## Judged answer quality (blind, opaque rotated labels, 5 substantive videos)
| Video | max | original | ours-balanced | ours-evidence |
|---|---|---|---|---|
| Ken Robinson | 4 | 4 | 4 | **2 (LOSS)** |
| Python OOP | 4 | 4 | 4 | 4 |
| Karpathy LLMs | 4 | 4 | 4 | 4 |
| repo roundup | 4 | **3** | 4 | 4 |
| Claude Code | 2 | 2 | 2 | 2 |
| **TOTAL** | **18** | **17** | **18** | **16** |

- **ours-balanced: 18/18** — perfect score at 23-42% fewer tokens than the original.
- **original dropped a point** on the roundup: captions-only, it garbled the repo name
  ("Claude Video"/"maltbot", never the exact slug); ours recovered `bradautomates/claude-video`
  from the description on both arms. The description-as-evidence feature is worth real points.
- **ours-evidence dropped 2 points on Ken Robinson**: chapter retrieval stopped at 15:08,
  just before the Gillian Lynne story (15:20) that the question explicitly asked about.
  A real retrieval miss, under analysis. Elsewhere evidence mode was 4/4/4/2 at -39% to -88%.
- Prior judged video (_cmpIveXnvE): 8/8 all three arms.

## Post-fix retest (v1.2.3, same frozen keys)
The Ken Robinson evidence-mode loss was root-caused (ASR caption track chosen
over the manual one + lexical retrieval blind to ASR spelling "jillian lynn")
and fixed in v1.2.3: manual-track preference, suffix normalization, zero-hit
fuzzy term matching, retrieval notes. Blind re-judge vs the frozen key: **4/4**
(was 2/4), at 6,089 tokens (-43% vs original). Other four evidence arms re-ran
with key-content probes intact and no spurious notes. Post-fix evidence-mode
corpus total: **18/18**. Detail: fix/ROOT-CAUSE.md.
