# EXIT — v1.5.8 criteria → evidence

| Criterion | Evidence |
|---|---|
| `--text-anchors` extracts bounded anchors at transcript-segment starts, end-to-end on real acquisition | `live-url-trace.txt` (6 anchors added, cap respected) + `EVIDENCE.md` |
| Explicit `--timestamps` keep precedence; anchors take only the remaining budget | `live-url-trace.txt` (3 manual + 6 anchor + 11 scene = 20, all manual preserved); `tests/test_text_anchors.py::test_resolve_manual_precedence_bounds_anchor_count`, `::test_explicit_timestamps_keep_precedence` |
| Exact 30% floor incl. 0 for caps 1–3 and correct for huge integer caps | `::test_exact_30pct_floor_is_zero_for_tiny_budgets`, `::test_floor_is_exact_integer_math_for_huge_caps` |
| Hostile/pathological caption track is bounded in anchor count AND memory | `::test_hostile_dense_track_is_hard_bounded_in_count`, `::test_scan_is_bounded_so_pathological_cue_count_cannot_burn_cpu` |
| Fails open (no captions / error) to normal extraction | `::test_resolve_no_captions_fails_open`, `::test_resolve_error_path_fails_open`; `verify.json` ARM B fail-open note |
| Latched off in evidence mode, incl. after evidence→balanced fallback | `::test_evidence_request_latches_anchors_off_through_fallback` |
| No default-path regression (additive-only) | `verify.json` ARM A≡B: identical 12-frame selection with the flag on but no captions vs default |
| Frame cap never exceeded | `verify.json` ARM C (2 cue + 3 scene ≤ 6); live trace (all runs total = cap) |
| `83da59f` scoring gate | Satisfied by construction: every change is gated behind `text_anchors_active`; the flag adds no scoring to the default path. ARM A≡B is the machine-checkable proof. Not a v2/v3 comparator change. |
| Provenance + credit truthful | PROVENANCE rows for `--text-anchors` (@48e1b7c) and the retroactive v2 row (@6f6c25f); CHANGELOG 1.5.8 entry |
| yt-dlp 403 now actionable (folded in per owner) | `tests/test_acquisition.py::test_informative_403_is_not_masked_by_a_noisier_retry`, `::test_acquisition_error_403_message_points_at_yt_dlp_upgrade`; verified live (`unknown` → `http_403 -- … pip install -U yt-dlp …`) |

## Scope records

- The dedup blind spot's real fix (denser bounded candidate supply + local-change
  scoring, as v3) is a SEPARATE benchmark-gated track, not this release. This
  release ships only the additive `--text-anchors` mitigation + the yt-dlp fix.
- The v0.7.16 "action channel" mechanism is logged for the v3 corpus, not adopted.

## Post-release verification

_Appended after tag:_ (pending)
