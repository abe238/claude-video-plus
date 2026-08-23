# EXIT — v1.5.5 video cache

Acceptance criteria (deep-pass plan P2, Codex-hardened) → evidence:

| criterion | evidence |
|---|---|
| Opt-in only, off by default persists nothing | tests: cache_disabled_by_default, cache_off_by_default_never_stores |
| URL-only, allowlisted YouTube hosts, exclusions outright (signed/private/cookie/credential + availability) | identity/probe-matrix/availability tests; SKILL.md hot-path contract |
| Source-index → verified digest, per-hit checksum | hit_bytes_are_proven_identical, corruption eviction tests, O_NOFOLLOW descriptor verification |
| Owner-only + Windows profile guard, no symlinks (objects, lock, ancestors) | permission/symlink/ancestor/lock test batteries |
| Atomic writes + locking + transactional inserts with deferred deletions | round-12/13 regressions |
| Bounds: per-entry, total LRU by verified size, TTL, headroom, oversized bypass, growth-abort | bounds battery incl. dishonest-row tests |
| Fail-open to fresh download on ANY failure, with notices | helper/exception boundary tests |
| Consent + WATCH_MAX_FILESIZE on misses unchanged; hit needs no consent | consent hit-vs-miss test |
| EvidenceState media refusal untouched | reviewer-verified each round; no state.py changes in diff |
| Live cold/hit + byte-identity + output equivalence | verify.json, hash-manifest.json, normalized cold/hit reports |
| Experimental marker (CONTRACTS.md incomplete-feature gate) | marker rendered hit/miss/store-exception in both modes; removal is a separately reviewed packet |

Formal scope record — `--ignore-config`: applied to EVERY acquisition
invocation (cache on or off), deliberately, as removal of an ambient
injection surface (a user-level yt-dlp config can add cookies/flags this
pipeline never agreed to; same class as the v1.2.4 cwd-`.env` removal).
Documented as a breaking change in CHANGELOG with a migration note;
owner-approved in session (2026-08-22). Default-path compatibility: the full
suite (incl. every acquisition command test) and the live runs above all
execute with the flag in place.

Protocol note: this packet uses the post-v1 release-evidence convention
added to PROTOCOL.md in this release (verify.json + SOL-REVIEW.md + EXIT.md
under docs/evidence/<version>-<slug>/, no packet registry).

Final verification (produced by the committed harness
`run-verification.py`; all exits 0; literal receipts in verify.json):
full suite **830 passed in 46.56s**, cache-focused
**115 passed in 1.46s**, live cold
3.3 s (1 download) → hit
2.3 s (0 downloads, verified-serving
banner), media + all 19 frame hashes identical (hash-manifest.json).

Post-release finalization (appended after tagging): released asset URL,
HTTP status, sha256.
