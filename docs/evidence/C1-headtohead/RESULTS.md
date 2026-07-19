# Head-to-head: v1.2.1 vs original v0.2.0 (83da59f)
Video: _cmpIveXnvE "Why the AI's honeymoon is ending" / Lenny's Podcast / 96 min / manual captions.
Question (evidence): "what does Noam Segal say about how AI is changing the work and morale of tech workers?"
Same machine, same network, measured end-to-end. Descriptive single-run, n=1 (not the preregistered bake-off).

| Metric | Original (83da59f) | Ours balanced (v1.2.1) | Ours evidence (v1.2.1) |
|---|---|---|---|
| Report tokens | ~51,232 | ~29,967 (-42%) | ~8,698 (-83%) |
| Transcript tokens | ~46,845 (2278 seg) | ~25,444 (1867 seg) | (chapters only) |
| Frames | 100 | 100 | 10 |
| Wall time | 91s | 91s | 40s (-56%) |
| Max coverage gap | 668s | 386s | (targeted) |

## Where the balanced token win comes from (equal frames!)
Rolling-caption overlap dedup: 2278 -> 1867 segments, ~47k -> ~25k transcript tokens. YouTube restates each caption line's tail in the next; original ships the duplication, ours collapses it losslessly.

## Coverage: same 100 frames, better placed
Ours max uncovered gap 386s vs original 668s (the v2 density floor). Original's scene sampler left a 11-min stretch of a 96-min video with no frame; ours halves the worst gap.

## Security (code-verified)
- Original renders manual captions RAW with zero sanitization and never reads the description.
- Ours neutralizes the injection fixture (END marker survives verbatim: False) across description/title/uploader/chapter/transcript, AND reads the description for spelling recovery (1/13 -> 13/13 on repo-name videos) which the original cannot do at all.

## Capability the original lacks entirely
Evidence mode: 8.7k tokens for a targeted answer vs the original's only option (51k full balanced). No original equivalent.
