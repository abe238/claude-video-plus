# Ken Robinson evidence-mode miss — root cause + fix (post-bake-off)

## Failure (blind-judged 2/4)
Evidence mode selected 6 chapters ending at 15:08; the question's Gillian Lynne
story lives in the final chapter `epiphany [15:08-20:03]`, which scored 0.000.

## Root cause (two independent links, both reproduced)
1. **Wrong caption track.** `_subtitle_candidates` sorted `video.en-orig.vtt`
   (ASCII `-` < `.`) ahead of the manual `video.en.vtt` and treated them as equal
   preference, so the pipeline consumed YouTube's ASR track even though the
   human-written track sat in the same directory. Reproduced: manual track ranks
   epiphany #1; ASR track ranks it 0.000 and reproduces the exact shipped selection.
2. **Lexical brittleness to ASR reality.** ASR spells "Gillian Lynne" as
   "jillian lynn" -> zero term overlap; "schools" vs "school" compounds. The
   existing span-rescue safety net breaks on score<=0, so it could not fire.

## Fix (v1.2.3), adversarially selected from 5 candidates
- **S1** manual-track preference (exact `.en.` before `.en-orig.`).
- **S2** suffix normalization (schools->school) + zero-hit fuzzy matching
  (question term absent from the ENTIRE transcript maps to the closest
  transcript token at edit distance <=1: gillian->jillian). Gated so healthy
  videos are bit-for-bit unaffected.
- **S4** unmet-term notes: a capitalized question term absent from selected
  evidence prints a report warning (first draft fired on framing words like
  "teaching" on every healthy video — tightened to proper-noun-like terms).
- **S3 (REJECTED by its verification gate):** rescuing lexical_rank top segments
  looked attractive until inspection showed its ASR-track "hits" were stopword
  noise ("big story mel gibson", "james robinson"). Not shipped.

## Re-test vs the frozen bake-off key
- Rerun selects `epiphany [15:08-20:03]`; report contains the full story
  ("Gillian Lynne" x8, manual spelling), 6,089 tokens (still -43% vs original).
- Other 4 evidence arms re-run: all key-content probes present, no spurious notes,
  tokens within noise of the originals runs.
- Suite: 483 passed (8 new regression tests).
