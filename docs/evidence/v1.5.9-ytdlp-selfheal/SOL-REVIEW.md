# SOL-REVIEW — v1.5.9 (yt-dlp self-heal)

Adversarial reviewer: Codex `gpt-5.6-sol`, `xhigh`, `--sandbox read-only`,
watchdog-guarded. Auto-installing software on a user's machine is a policy shift
from the skill's "detected, never installed" default, so it was reviewed as a
security change.

## Round 1 — BLOCK, 5 findings (all fixed)

1. **Module/pip resolution shadowing.** `python -m pip` / `python -m yt_dlp` were
   exposed to a planted `pip`/`yt_dlp` in the CWD or via `PYTHONPATH`, and pip
   honored ambient `PIP_INDEX_URL`/`PIP_CONSTRAINT`/`PIP_CONFIG_FILE`, so the
   source/version/deps of the install were not guaranteed to be official yt-dlp.
   → Fixed: `_hardened_python()` adds `-E` (drops PYTHON* env) and `-P` (3.11+,
   drops the unsafe `sys.path[0]`); pip runs `--isolated` with an explicit
   `--index-url https://pypi.org/simple/`, in the trusted scripts CWD, with a
   `_hardened_subprocess_env()` that strips PYTHON*/PIP_*. Applied to the forced
   `python -m yt_dlp` path too. Fixed argv, no untrusted input.

2. **`.env` opt-out broken.** `ytdlp_autoupdate_enabled()` read only `os.environ`,
   so `WATCH_YTDLP_AUTOUPDATE=0` in `~/.config/watch/.env` did nothing.
   → Fixed: env-over-file lookup; `download_url` passes `read_env_file()`.
   Integration test exercises the file opt-out through the production wiring.

3. **Post-upgrade preservation.** State was flipped without proving the module
   runs, and a fatal retry overwrote the original actionable error.
   → Fixed: probe `-m yt_dlp --version` before trusting; a still-fatal retry
   keeps the original `http_403` result; pip output goes to DEVNULL (no
   `text=True` decode risk).

4. **"Once" was per-call, not per-process.** Evidence-mode / repeated library
   calls could reinstall.
   → Fixed: lock-guarded `_upgrade_attempted` latch — at most one install per
   process, success or failure.

5. **Cache race + missing disclosure.** `_FORCE_MODULE` + `lru_cache.cache_clear`
   raced; auto-install wasn't in the always-loaded Security section.
   → Fixed: split into an uncached `ytdlp_cmd()` (checks the flag under the lock)
   and a cached `_detect_ytdlp_cmd()`; disclosure added to SKILL.md Security.

## Verification
Focused self-heal tests (8), Windows-fallback tests (12), full suite (894), and
a LIVE `upgrade_ytdlp()` that forces a runnable `python -E -P -m yt_dlp`
(2026.08.19) — see `verify.json`. Round-2 confirmation verdict recorded in
`EXIT.md`.
