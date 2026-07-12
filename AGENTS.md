# claude-video / watch skill

Agent Skills package that gives an agent a video input. Installable across Claude Code (most common host), Codex, Cursor, GitHub Copilot, and 50+ other [Agent Skills](https://agentskills.io) hosts. Pure-stdlib Python that orchestrates `yt-dlp` + `ffmpeg` and an optional Whisper API.

## Structure

- `skills/watch/SKILL.md` — canonical skill contract the model reads when `/watch` fires. Source of truth for behavior across every host.
- `skills/watch/scripts/watch.py` — entry point; orchestrates download → frames → transcript.
- `skills/watch/scripts/{download,frames,transcribe,whisper,setup,config}.py` — yt-dlp wrapper, ffmpeg frame extraction + auto-fps, caption/Whisper transcription, preflight/installer, shared config.
- `skills/watch/scripts/build-skill.sh` — builds `dist/watch.skill` for claude.ai upload (dev-only).
- `hooks/` — Claude Code SessionStart setup-status hook (Claude Code only).
- `.claude-plugin/` — `plugin.json` + `marketplace.json` (Claude Code plugin + local marketplace).
- `.codex-plugin/plugin.json` — Codex/agents manifest; `"skills": "./skills/"` points the Agent Skills CLI at the self-contained skill folder.
- `.agents/plugins/marketplace.json` — agents marketplace listing pointing at the repo-root plugin.
- `CLAUDE.md` → `@AGENTS.md` — generic-agent entry point.
- `tests/` — pytest suite (ffmpeg-synthesized clips; no network).

## Orientation

- The product is the slash-command-invoked skill (`/watch <url-or-path> [question]`), not a CLI. `scripts/watch.py` is implementation. Features must work across every harness the skill installs into, not just Claude Code.
- **The skill is one self-contained folder: `skills/watch/`.** SKILL.md and `scripts/` are siblings inside it. This is what lets `npx skills add` copy a working skill as a unit — do NOT move SKILL.md or `scripts/` back to the repo root, or non-Claude installers will copy SKILL.md without the scripts.
- **Path resolution is harness-agnostic.** SKILL.md resolves `SKILL_DIR` as the directory of the SKILL.md the model just Read, then runs `${SKILL_DIR}/scripts/...`. Do NOT reintroduce `${CLAUDE_SKILL_DIR}` (Claude-Code-only) — it is unset on Codex/Cursor/agents and breaks every script call there.
- **No `commands/` wrapper.** `/watch` is derived from SKILL.md frontmatter (`name: watch` + `user-invocable: true`). A separate command file creates a duplicate slash command.

## Install surfaces

| Surface | Install |
|---------|---------|
| Claude Code | `/plugin marketplace add abe238/claude-video-plus` then `/plugin install watch@claude-video-plus` |
| Codex / Cursor / Copilot / +50 | `npx skills add abe238/claude-video-plus -g` |
| claude.ai (web) | upload `dist/watch.skill` (built by `skills/watch/scripts/build-skill.sh`) |

## Commands

```bash
# Tests (stdlib + pytest; ffmpeg required for frame tests)
.venv/bin/pytest -q                # or: python3 -m pytest -q

# Single test file / test function
python3 -m pytest -q tests/test_frames.py
python3 -m pytest -q tests/test_frames.py::test_dedup_drops_near_identical_frames

# Build the claude.ai upload bundle (archives skills/watch/ as the bundle root)
bash skills/watch/scripts/build-skill.sh   # → dist/watch.skill

# Dev: mirror the working tree into the installed Claude Code plugin cache
./dev-sync.sh                       # --dry-run to preview
```

No lint/type-check config exists (pure-stdlib Python, no pyproject.toml) — pytest is the only gate.

## Architecture note

`watch.py` is a linear orchestrator today (download → frames → transcript → report), with `SKILL.md` carrying most of the intelligence as agent instructions. `docs/ARCHITECTURE.md` describes an in-progress, benchmark-gated redesign toward a query-aware "Scout → Retrieve → Verify" evidence compiler. `docs/plans/V1.0-MASTER-PLAN.md` is the canonical execution plan. The two older evidence-backed plans are historical research and adversarial-review records, not implementation instructions. Changes to selection/scoring code must be measured against the frozen control commit `83da59f`, not merged on intuition. `CONTEXT.md` defines the domain vocabulary (**Evidence span**, **Evidence budget**, **Evidence manifest**, etc.) used across those docs — read it before naming new concepts in this area.

Execution follows `docs/execution/v1/PROTOCOL.md` and `docs/execution/v1/CHAIN.md`.
Terra implements bounded, disjoint requirement slices. Under the owner's implementation-first
direction, finish P02–P32 implementation before beginning consolidated tests, benchmarks,
install/bundle verification, and independent review. P32 must close every release blocker before
publication.

## Rules

- Keep the version in sync across `skills/watch/SKILL.md` (frontmatter), `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` when cutting a release.
- Releasing: tag `vX.Y.Z` and push the tag; `.github/workflows/release.yml` builds `dist/watch.skill` and attaches it to the GitHub release.
- Never commit real API keys or `.env` contents; keys live in `~/.config/watch/.env` (mode `0600`) at runtime.
- Preserve the easy install surfaces: Claude Code marketplace/plugin, `npx skills add <owner>/<repo> -g`, the release `watch.skill`, and the manual `skills/watch` symlink.
- Keep `skills/watch/` self-contained. New large runtimes or models must remain optional unless reproducible benchmarks justify making them required.
- Do not add OpenCV, PySceneDetect, an OpenCV installer choice, or an OpenCV runtime Adapter. The measured ablation in `docs/benchmarks/2026-07-11-opencv-ablation/` rejected that direction; use FFmpeg plus standard-library Python for vision scoring.
- Measure optimization claims against the untouched upstream control commit `83da59f`; do not claim an improvement from intuition or proxy metrics alone.
- Owner-directed work may commit directly to `main` for now. Future outside contributions should use a branch and pull request.
- Preserve prominent, appreciative attribution to Brad Bonanno and `bradautomates/claude-video` in public-facing repository material.

## Agent skills

### Issue tracker

Work is tracked in GitHub Issues for `abe238/claude-video-plus`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context layout with `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.
