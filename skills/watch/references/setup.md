# /watch — setup, first run, and remediation

Read this when `setup.py --check` exits non-zero, on a genuine first run, or
when the user asks about configuring a transcription backend. A run where
`--check` exits 0 never needs this file.

**Secret handling (repeated from SKILL.md because it is binding here):** never
ask the user to paste, reveal, or transmit an API key in chat, and never
accept, echo, interpolate into a command, or write a secret on their behalf.

---

On the first `/watch` invocation in a session, use structured preflight so you can detect first-run setup:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --json
```

Branch on two fields:

- **`can_proceed: true` and `first_run: false`** → setup is already done (the user may have deliberately skipped a Whisper key — that's allowed). Proceed to Step 1 without comment.
- **`first_run: true`** → genuine first-time setup. Do these in order:
  1. If `missing_binaries` is non-empty, run the installer first (it auto-installs on macOS / prints commands elsewhere — see below) and confirm the binaries land. **Do not skip this and jump to preferences.**
  2. Run the installer once more if needed so it scaffolds `~/.config/watch/.env` (it only writes a blank template and never handles a secret).
  3. Explain the optional local API-key setup below, ask the non-secret watch-preference question, write only that preference, and set `SETUP_COMPLETE=true`.
- **`can_proceed: false` and `first_run: false`** → setup was finished before but the environment regressed (e.g. `missing_binaries` after an OS change). Run the installer to remediate, then proceed. Don't re-ask preferences.

A transcription backend is *encouraged, not required*, and **a cloud key is the last resort, not the first**. `status` reads `needs_key` only when there is no backend at all: no reachable local STT server, no YAP, and no cloud key. If `local_stt` is non-empty the setup is already `ready` — do not ask for a key. A cloud key on its own transcribes nothing anyway: the cloud Adapters refuse without `--allow-remote-transcription` (or `WATCH_STT_ALLOW_REMOTE=true`).

On non-zero exit, follow the table:

| Exit | Meaning | Action |
|------|---------|--------|
| `2` | Missing binaries (`ffmpeg` / `ffprobe` / `yt-dlp`) | Run installer |
| `3` | Genuine first run with **no transcription backend at all** (no local server, no YAP, no cloud key) | Run installer to scaffold `.env`, then suggest a backend **in runtime order**: a local STT server on `127.0.0.1:8082`, or YAP on macOS (`brew install finnvoor/tools/yap`). Mention cloud last, and only with the caveat that a key does nothing without `--allow-remote-transcription`. The user may decline — proceed with `--no-whisper` |
| `4` | Both missing | Run installer, then suggest a backend as above |

Exit `3` only fires before the user has completed setup. Once `SETUP_COMPLETE=true` is written, a keyless install returns exit 0 and is never nagged again.

The installer is idempotent — safe to re-run:

```bash
python3 "${SKILL_DIR}/scripts/setup.py"
```

On macOS with Homebrew, it auto-installs `ffmpeg` and `yt-dlp`. On Linux/Windows, it prints the exact install commands for the user to run. It scaffolds `~/.config/watch/.env` with commented placeholders and default watch settings at `0600` perms.

**If no transcription backend exists after install:** suggest the local ones first, because they need no secret and no network. On macOS that is `brew install finnvoor/tools/yap`; on any platform it is a local OpenAI-compatible STT server on `127.0.0.1:8082`. Only if the user actively wants cloud Whisper, tell them a key alone is inert (the cloud Adapters refuse without `--allow-remote-transcription` / `WATCH_STT_ALLOW_REMOTE=true`) and that audio would leave their machine.


**First-run watch preference:** after the installer has scaffolded `~/.config/watch/.env`, use `AskUserQuestion` to ask one question:

- Default detail (one dial). Present these as `AskUserQuestion` options in this exact order — lightest to heaviest — and keep `(recommended)` on `balanced` even though it is not first (do **not** reorder to put the recommended option first):
  - `transcript` — no frames at all, transcript only (skips video download when captions exist).
  - `efficient` — fast keyframe pass (cap 50).
  - `balanced` (recommended) — scene-aware frames (cap 100, default).
  - `token-burner` — scene-aware, uncapped (maximum fidelity; high token cost).

Write the answer directly into `~/.config/watch/.env` by setting the bare key on its own line — **no trailing inline comment** (a `# note` after the value can break parsing):

```bash
WATCH_DETAIL=balanced
```

Use the user's selected value. If they skip the question, keep the recommended default. Once dependencies, private API-key guidance, and this preference are handled, write or update `SETUP_COMPLETE=true` in the same file. Do not ask this preference question again when `SETUP_COMPLETE=true`.

**Structured mode (optional):** `python3 "${SKILL_DIR}/scripts/setup.py" --json` emits `{status, can_proceed, first_run, setup_complete, missing_binaries, whisper_backend, has_api_key, local_stt, config_file, watch_detail, platform}` where `status` is one of `ready | needs_install | needs_key | needs_install_and_key`. `local_stt` lists the local Adapters detected right now (`local-http`, `yap`) — a non-empty list means transcription is already covered and `status` is `ready` with no key. `can_proceed` is the operational gate (binaries present AND some transcription backend exists OR setup was already completed). Branch on `can_proceed`/`first_run` to decide whether to run; use `status` and `local_stt` to decide what, if anything, to suggest.

Within a single session, you can skip Step 0 on follow-up `/watch` calls — once `--check` returned 0, nothing about the environment changes between turns.
