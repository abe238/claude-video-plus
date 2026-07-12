# 0.3.0-rc.1 early-publish audit

Reviewed implementation commit: `c0efe180b1d8f0afdf38a7cb9297cba6977038e9`

Published prerelease: [`v0.3.0-rc.1`](https://github.com/abe238/claude-video-plus/releases/tag/v0.3.0-rc.1)

## Acceptance evidence

| Check | Result |
| --- | --- |
| Complete local deterministic suite | 327 passed: 82 Control/conformance, 61 media/runtime, 184 contracts/state/release |
| Hosted matrix | 5/5 passed: macOS 14 Python 3.11/3.12/3.14; Ubuntu 22.04 Python 3.11; Ubuntu 24.04 Python 3.12 |
| Agent Skills lifecycle | Disposable clone and HOME: local source add with `--copy -g -a codex`, diagnostics invocation, removal, installed-root removal, source preservation |
| Skill validation | `quick_validate.py skills/watch`: valid |
| Bundle | 20 allowlisted runtime files; 81,952 bytes; deterministic SHA-256 `7636dbc7510736b2b71e3607af46ff115ff9a7d7b9eff1e0d55ea1d0e704981f` |
| Registry/compilation | 45 requirements and 35 packets valid; all Python compiles |
| Independent review | `APPROVE_EARLY_PUBLISH`; no remaining prerelease blocker |
| Hosted CI | [successful Actions run](https://github.com/abe238/claude-video-plus/actions/runs/29204504396) |

## Boundary

This audit authorized only a clearly labeled `0.3.0-rc.1` prerelease, which was subsequently
tagged and published without changing repository visibility. The release and artifact remain
private to authorized GitHub users. Stable v1.0, public visibility, and broad superiority claims
remain blocked on multi-video Pareto evidence, human grader validation, the authorized sealed
confirmation run, and the owner's later publication decision.
