# SOL-REVIEW — v1.5.5 video cache (Codex gpt-5.6-sol, xhigh, read-only)

Seventeen review rounds against the live diff. Every BLOCK finding was fixed
with a regression in `tests/test_video_cache.py` (or docs corrected) before
the next round. Dispositions:

| round | verdict | findings → disposition |
|---|---|---|
| 1 | BLOCK | poisoned-index unlink outside cache → validated digest/suffix/direct-child; exclusion bypass (http, YouTube token params) → HTTPS-only + benign-param allowlist; dedupe/eviction conflict → refcounting; interrupted writes → exclusive temporaries + full finally; lock staleness → (superseded round 3 by OS lock); TOCTOU → O_NOFOLLOW descriptor I/O; evidence-mode + notice integration; index URL privacy → sanitized in insert |
| 2 | BLOCK | exact-cap latch; provenance rows pinned; complete-rescue guidance; focused-range/local-after-cloud/provider-fallback test authenticity; dataclass; stamp-consumer pin (carried from v1.5.3 series review lineage) |
| 3 | BLOCK | fail-open completeness (isfinite, scalar validation, helper boundaries); config-mutation seam → insert-time revalidation; steal-race → OS-backed advisory lock |
| 4 | BLOCK | collision accepted 0644 object → owner-only+size+digest validation; cold-run marker; SKILL.md hot-path scope text; FIFO hang → O_NONBLOCK+fstat; atomic squatter replacement |
| 5 | BLOCK | shared-object corruption eviction (_evict_object) + collision verify; private hosts → YouTube-only scope; benchmark provenance labels |
| 6 | BLOCK | collision owner-only; cold marker on every participating run; SKILL.md 'private' + scope; FIFO/no-follow helpers; atomic replace |
| 7 | BLOCK | strict key shapes (port/paths); marker survives store exceptions; growing sources; Windows lock fallback |
| 8 | BLOCK | v-cardinality/raw-path/ASCII-id/port parsing; O_EXCL lock creation; growth vs headroom; index query stripping |
| 9 | BLOCK | availability visibility (public-only store+hit); index size trust → verified st_size; lock O_NONBLOCK both branches; hit provenance line; corrupt-index reset; --ignore-config owner approval |
| 10 | BLOCK | probe REQUIRED for hits (+cookie_used is False); lock owner-only both branches; probe-matrix/bounds/lock regressions |
| 11 | BLOCK | _publicly_available type-safety; sharpened bounds/LRU test mechanisms |
| 12 | BLOCK | transactional insert (fresh-object rollback); release evidence packet required |
| 13 | BLOCK | deferred deletions past index commit; ancestor-symlink refusal; full hash manifests + exact commands + this file + EXIT.md; --ignore-config formal scope record |
| 14 | BLOCK | purge/inspect lacked tree validation + lock → _validate_tree shared, purge serializes under the writers' lock and keeps root/lock (3 regressions incl. live-writer serialization); receipts made literal (exact commands, integer exits, final counts) from a fresh instrumented run |
| 15 | BLOCK | ancestor-symlink test now seeds valid target-side data + sentinel and byte-snapshots the target; receipts now produced by the COMMITTED executable harness (run-verification.py: mkdtemp paths, timing/download-count collection, normalization, full hash method); review-history count corrected; duplicate Windows check deduped into _validate_tree |
| 16 | BLOCK | harness hardened: allowlisted env with ISOLATED HOME (purges can never touch real user state — the live run itself then proved the ancestor-symlink defense by refusing macOS's /var symlink until the harness resolved its temp path), purge_after recorded and gated, ok requires exactly-1 cold download / 0 hit downloads / both report markers / exact banner / non-empty identical frame NAME SETS (no zip), actual work paths normalized |
| 17 | BLOCK | harness probes made argv-based under the isolated env while the temp home exists (shell=True removed); Windows-only env vars qualified; acceptance gates made EXACT-LINE (splitlines().count == 1 for the full banner incl. [watch] prefix + …, both complete marker lines, the download line 1/0 cold/hit) with matched lines recorded; P4 artifacts + v1.5.6 plan to be committed separately from the release commit |
| 18 | NOT COMPLETED | the reviewer infrastructure hung on three consecutive attempts (watchdog-killed at 15 min each; two other hangs earlier the same day). Ship decision taken on the owner's standing directive with: rounds 16–17 explicitly confirming the cache runtime matches P2, round-17 findings limited to verification-harness polish (all implemented and re-verified: harness ok=true, exact-line gates, isolated argv probes), 830-test suite green, and the isolated live byte-verified acceptance. Residual risk: the final harness polish did not receive independent re-review |

The reviewer independently verified the live-run media sha256
(e25bcad888afc039e27d316da0471ea08199ed2cf0f424cffd46d05a7902c998) and all
19 cold/hit frame-hash pairs in round 13.
