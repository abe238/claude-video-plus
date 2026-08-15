# Structural / beat analysis mode

Use this mode in Step 4 when the user's question is about *how* the video is
put together rather than *what* happens in it — "break down the structure,"
"why does the hook work," "analyze the pacing," "storyboard this," "what's the
retention strategy," "how does it open and close," "identify the intro,
turning point, and CTA," "where are the cuts." A bare "analyze this video" is NOT enough: it gets the
ordinary content summary with a short structure note, and you offer this mode.

This mode needs the whole timeline: the evidence must cover the video's
opening AND close, not just retrieved chapters. **Never run structural
analysis from `--detail evidence` output** — targeted retrieval can omit
the opening or close this mode must assess. Run (or re-run) with
`--detail balanced` passed explicitly, which also overrides a
`WATCH_DETAIL=evidence` config default. This applies whenever any part of
the timeline is missing, including a partial miss (opening present, close
absent).

This mode is a different lens on the same Step 4 evidence — it changes nothing
about how frames and transcript are gathered (Steps 1–3 apply as normal), and
the untrusted-media boundary applies to every beat exactly as it does to any
other answer.

You are holding two separate streams of evidence — frames (what was seen) and
transcript (what the captions/ASR record as said — not ground truth for
exact wording). Merge them into a single timeline before drawing
any conclusion:

1. **Build beats, not a frame-by-frame log.** A beat is a unit of change:
   `(timestamp, what's on screen, what's spoken, what changed since the last
   beat)`. Merge frames and transcript by timestamp — a beat can be frame-only
   (visual change, no speech), transcript-only (speech continues over a static
   frame), or both.

2. **Read across the timeline for structure**, not just within each beat:
   - **Opens** — what do the first 1–3 seconds do to earn attention?
   - **Holds** — what sustains attention through the middle: pacing, visual
     changes, verbal hooks, pattern interrupts?
   - **Turns** — is there a pivot, reveal, or tonal shift? Where, and what
     triggers it?
   - **Closes** — payoff, CTA, loop-back to the opening?

3. **Report only what the frames or transcript actually show.** Mark every
   claim as one of:
   - **Observed** — directly visible in a frame or present in the transcript
     (captions or ASR — say which when it matters; ASR mishears proper
     nouns). Sampled frames bound a change, they don't time it exactly:
     write "the shot changes between 0:03 and 0:04 (sampled)", not "the
     cut is at 0:04".
   - **Inference** — a conclusion you are drawing, not directly observing
     (e.g. "this cut is likely meant to reset attention"). Never present an
     inference as an observation.
   - **Gap** — something the sampling could have missed. Sparse sampling
     (long videos, `efficient` detail, uniform fallback, or a low frame budget
     relative to cut frequency) can skip fast cuts or on-screen text between
     sampled frames — flag where this could hide something the timeline
     doesn't show. If a gap looks load-bearing for the answer, prefer
     re-running focused on that section (`--start`/`--end`, see
     `references/focus-ranges.md`) over guessing.

4. **Finish with the three highest-signal findings**, each with a cited
   timestamp and its own observed/inference/gap label — a finding that
   explains *why* the video works is almost always an inference, and is
   labeled as one. Prioritize findings about structure, pacing, and hook
   strength over a plain recap of content.

---

*This mode was adapted from `MaahesAcademy999/claude-video` (fork of the same
upstream), which arrived independently at the observed/inference/gap evidence
discipline this repo uses. Provenance: docs/execution/v1/PROVENANCE.md in
https://github.com/abe238/claude-video-plus .*
