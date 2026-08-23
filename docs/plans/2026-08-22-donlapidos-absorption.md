# donlapidos absorption plan → v1.5.6 (2026-08-22)

Source: `donlapidos/claude-video` (+5, Snyk-audit-driven security fork,
W007 credential handling HIGH + W011 injection containment MEDIUM, with
their own 25-test containment suite). Security gate: PASSED (read-only
audit; patches are defensive, no phone-home, no new deps, no exec surfaces).

## Cross-check verdicts

Already ours (parallel evolution, no port): ffmpeg `-vsync` probe (v1.3.5,
ours has the <5.1 fallback theirs lacks), Windows permission-bit fix
(v1.3.3→v1.3.6), UTF-8 console (v1.3.5), `--ignore-config` (v1.5.5),
`--no-playlist` + `--max-filesize` (v1.3.0), credentialed-URL refusal,
"never handle a key" SKILL.md rule (their W007 core), key-safe setup.md.

Deliberately NOT ported: `--no-cookies`/`--no-cookies-from-browser` (we
gate cookies behind validated `WATCH_COOKIES_BROWSER` — a feature, not an
accident; cookie-fetched media is already barred from the cache);
nonce-delimited markers (our defense DEFANGS marker-like content instead —
content can never impersonate a boundary it cannot spell); removing
`AskUserQuestion` (ours is needed for the non-secret first-run preference;
the key rule already bars secret use).

REAL GAPS found in ours (the steal):

1. **Report sanitizer misses three vectors** (`download.sanitize_for_report`):
   - C0/C1 control bytes and ANSI escape sequences (our `strip_invisible`
     covers category Cf, controls are Cc) — terminal-escape smuggling.
   - Harness-style tag impersonation: `<system-reminder>`, `<invoke>`,
     antml-style tags — a transcript can currently carry them verbatim into
     the report.
   - Chat-turn-marker impersonation: line-leading `Human:` / `Assistant:` /
     `System:` (including immediately after a `[MM:SS]` stamp).
2. **`--no-exec`** on every yt-dlp invocation (config-driven exec is already
   dead via `--ignore-config`; this closes the CLI-surface sibling).
3. **`setup.py --set-key groq|openai`**: hidden `getpass` entry that refuses
   a key in argv (process table), requires a TTY, bounds the read, validates
   shape, never echoes, re-asserts 0600 — so users stop hand-editing `.env`
   (or worse, pasting keys into chat when hand-editing frustrates them).
   SKILL.md/setup.md relay the command; the agent still never touches keys.
4. **Stale doc fix**: our SKILL.md "Data & privacy" line still ADVERTISES a
   cwd-`.env` fallback that v1.2.4 removed from code — misdocumentation of a
   fixed vulnerability; delete the claim.

Skips this sweep: `mouatasssim/chatgpt-video` (ChatGPT-sandbox port,
off-mission; its "no-key transcript fallback" parallels our captions path);
`menglebrecht` + `dustymurph` (6th/7th `-vsync` repeats); `micahwaterbury18`
(a 3D penguin game built in a fork — noise).

## Execution order

0. **Ship v1.5.5 first** (video cache + P4 receipts; through its Codex
   review rounds — see docs/evidence/v1.5.5-video-cache/SOL-REVIEW.md).
1. **v1.5.6 implementation** (each item with tests):
   - Sanitizer: extend the existing chokepoint (never a parallel one) with
     Cc/ANSI stripping and ZWSP-defusal of harness tags and turn markers,
     property-based where possible (category Cc wholesale; tag defusal by
     shape, not an enumerated tag list). Port their hostile-VTT end-to-end
     fixture idea: one adversarial caption file exercising every vector
     through a real `watch.py` run.
   - `--no-exec` in `build_yt_dlp_command` + command test.
   - `setup.py --set-key` with all five safety properties + tests (argv
     refusal, non-TTY refusal, shape validation, 0600, no echo).
   - SKILL.md line-168 doc fix (and re-check the ≤20k budget).
2. **Verify**: full local suite; hostile-fixture tests both directions
   (attacks defused, benign text with `<b>` tags / "Human:" quotes in
   legitimate dialogue survives readable).
3. **Live regression on the standard control video** (`jNQXAC9IVRw`, the
   original zoo clip): full `watch.py` run pre-tag, byte-checked frames,
   transcript present, report structure intact — confirming nothing in the
   sanitizer changes broke normal output.
4. **Codex gpt-5.6-sol xhigh gate** on the diff (as many rounds as it takes).
5. **CI matrix green (ubuntu/macos/windows) → tag v1.5.6 → verify release
   workflow + asset HTTP 200 live.**
6. Provenance + CHANGELOG credit (donlapidos, Snyk audit lineage), backlog
   rows to SHIPPED.
