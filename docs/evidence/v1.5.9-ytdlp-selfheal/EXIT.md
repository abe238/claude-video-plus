# EXIT — v1.5.9 criteria → evidence

| Criterion | Evidence |
|---|---|
| Self-heal upgrades yt-dlp on a stale-signature media failure and retries | `download_url` wiring; `tests/test_acquisition.py::test_download_url_self_heals_on_stale_403`; live proof in `verify.json` (`live_upgrade`: True → `-E -P -m yt_dlp` runs 2026.08.19) |
| pip argv is injection-free, isolated, official-index, hardened | `::test_upgrade_ytdlp_success_is_hardened_and_forces_fresh_module` (asserts `-E`, `--isolated`, official index, fixed `--user --upgrade yt-dlp`) |
| No planted-module / ambient-config redirection (supported Python 3.11+) | `_hardened_python` (`-E`; `-P` on 3.11+, the whole support matrix), `_hardened_subprocess_env` (strips PYTHON*/PIP_* AND pins `PIP_CONFIG_FILE=os.devnull` so global/site pip.conf is ignored too), trusted `_SAFE_CWD`; applied to the forced `-m yt_dlp` path. Hostile-config regression: `::test_upgrade_ytdlp_success_is_hardened_and_forces_fresh_module` sets `PIP_INDEX_URL`/`PIP_EXTRA_INDEX_URL`/`PYTHONPATH` and asserts the child env drops them. (3.10 lacks `-P` and is outside the support matrix, so its residual CWD-shadowing is out of scope.) |
| Upgrade trusted only after it proves runnable | `::test_upgrade_ytdlp_rc0_but_module_unrunnable_returns_false` |
| At most one install per process | `::test_upgrade_ytdlp_is_latched_once_per_process` (pip called once across two calls) |
| `.env` opt-out honored through production wiring | `::test_download_url_optout_via_env_file_skips_selfheal`; `::test_ytdlp_autoupdate_enabled_default_and_optout` (env-over-file) |
| Fatal retry preserves the actionable error | `::test_download_url_fatal_retry_preserves_original_actionable_error` (raises `http_403`, not `unknown`) |
| Degrades safely offline / PEP 668 / no pip | `::test_upgrade_ytdlp_failure_returns_false_and_does_not_force_module`; download_url prints the managed-env note |
| Cache race removed | uncached `ytdlp_cmd()` + cached `_detect_ytdlp_cmd()` under `_ytdlp_state_lock` |
| Auto-install disclosed in always-loaded contract | SKILL.md Security & Permissions bullet (19,996/20,000 chars) |
| Default-on defensible | explicit owner directive ("update yt-dlp as part of the process, always") + opt-out + disclosure |
| Version 1.5.9 coherent | both manifests, SKILL.md, and both pinned release tests |
| No regression | full suite 894 passed (`verify.json`) |

## Scope note
The self-heal drives the pip `--user` copy (the portable install path); it
cannot upgrade a brew/pipx binary, so on success it forces `python -m yt_dlp`
(the fresh copy) for the rest of the run. Users who pin yt-dlp deliberately set
`WATCH_YTDLP_AUTOUPDATE=0`.

## Post-release verification
_Appended after tag:_ (pending)
