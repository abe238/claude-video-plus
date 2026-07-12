# P02 — Candidate compatibility conformance and cheapest-Control routing

## Frozen inputs

- Master-plan commit: `edc2ce6696a88501f19060cc2000ed4f513c6133`
- Requirements: `CTRL-002`, `CTRL-003`
- GitHub issue: `#4`
- Frozen Control: `83da59fa78c3eee9e20f515fe75c438bb5166efd`
- Prerequisite packet: P01 and `tools/control_harness.py`

## Observable outcome

`tools/control_conformance.py` has two non-overlapping boundaries:

1. `route_control(RoutingRequest)` emits versioned, machine-readable cheapest-Control
   routing using only complete Question text, explicit supported detail, explicit
   timestamps, mirrored supported flags, and declared source identity metadata.
2. `run_pair()` runs a complete P01 case against the clean detached Control and the
   current Candidate in SHA-256 case-ID alternating order, then rejects every
   non-declared behavioral difference.

## Ownership and limits

Owned paths are `tools/control_conformance.py`, `tests/test_control_conformance.py`,
this packet, and `docs/evidence/v1/P02-conformance/**`. Runtime, `REQUIREMENTS.json`,
Control, P00/P01 evidence, and public documentation are off limits. This packet does
not declare a quality or performance improvement.

## Owner-directed single-pass rule

P02 receives one comprehensive implementation pass using all prior Sol P1 findings as frozen
input, then focused P02 tests, compilation, P02 validators, diff, and secret scans only. P32
owns the consolidated full-suite audit. A resulting Sol review is the packet's sole review pass;
this packet neither stages nor self-approves.

## Routing contract and refusals

Routing version is `cheapest-control-v1`. The first matching `CONTROL.md` rule wins:

| Rule | Pre-outcome condition | Effective frozen-Control detail |
| ---: | --- | --- |
| 1 | explicit supported detail | exact selected detail |
| 2 | explicit `--timestamps` | `transcript` |
| 3 | Question requests visible UI/text/table/object/motion/transition/before-after | `balanced` |
| 4 | Question requests coverage/summary/all topics/chronology | `balanced` |
| 5 | Question asks what was said/explained without a visual requirement | `transcript` |
| 6 | other Question or no Question | `balanced` |

The `RoutingRequest` type and CLI document schema have no gold, transcript, chapter,
Evidence span, score, result, or outcome field; the function has no `**kwargs` escape
hatch. Unknown detail, blank/ambiguous/invalid timestamps, invalid numeric/range/boolean
flags, whisper/no-whisper conflict, unsupported flags/metadata, or a disagreement between
timestamps and mirrored flags is an integrity refusal. Mirrored `timestamps` is itself a
supported boundary input and activates rule 2. The decision
records `schema_version`, `routing_version`, `matched_rule`, and all effective frozen
Control flags. `--start`, `--end`, resolution, frame cap/fps, whisper/no-whisper, and
dedup are mirrored unchanged.

## Conformance contract and refusals

For each deterministic local fixture, P02 requires the complete P01 source/tool/reader
pin record, a clean detached Control before and after, separate empty control/candidate
output and receipt directories, matching isolated environments, and P01's paired order.
It compares exit/failure/timeout classes; normalized stdout/stderr; transcript timestamps;
frame count, timestamps, dimensions, and order; output manifests; categorized failure and
fallback order; and wrapper-observed process/provider-network call counts. The Python observer
wrapper records each arm's actual watched-script start/end interval. Its per-arm `sitecustomize`
audit records and structurally blocks direct socket/urllib network and arbitrary subprocess or
`os.system` paths; wrapper-spawned absolute executables are also recorded. Latency compares payload
to payload rather than P01 setup to a Candidate child. Both arm no-op samples are preserved;
the allowance is `max(5 ms, 5% Control payload wall time, Control no-op p95−p50)`.

Only declared temporary roots and the single explicit evidence-fallback warning can differ.
Unknown absolute paths are refusals and every manifest byte difference blocks; no broad
provenance allowance exists. The tool refuses
dirty/wrong Control, source/tool pin drift, mismatched/empty arm directories, unsupported
allowed differences, missing no-op measurements, an unpaired case, extra Candidate provider
call/process difference, latency above the allowance, Candidate/repository/index/runtime pin
mismatch, or a behavioral mismatch. It never patches Control.

The evidence-fallback proof directly runs the installed Candidate on a generated local clip
with `--detail evidence --question`: local evidence prerequisites fail, exactly one warning
states the fail-open disposition, then the resulting balanced behavior is normalized against
Candidate balanced and frozen-Control balanced. `--no-whisper` and local input make provider
and network calls zero in this fixture.

## Tests and live proof

`tests/test_control_conformance.py` covers every routing priority, precedence and mirrored
flags, strict outcome-input refusal, P01 order reuse, strict root-only path normalization,
manifest/process/provider difference rejection, latency prerequisites/formula, deterministic
success/failure/timeout/fallback-order fixture pairs, and the real local evidence fail-open
path (single warning/observed no provider call).

The provisional live receipt records a generated local clip by SHA-256 only (no media or
absolute local path), current Candidate balanced/evidence and frozen Control balanced results,
sanitized raw stdout/stderr, command argv, wrapper-observed calls, raw-output digests/manifests,
Candidate commit/index/runtime identity, executable pins, no-op samples/formula inputs,
failure/timeout/fallback receipts, and the deterministic allowance. It contains no executable
symlink, media, secret, or private absolute path.

## Verification and bounds

```text
python3 -m pytest -q tests/test_control_conformance.py
python3 -m pytest -q
python3 -m compileall -q skills tools tests
python3 tools/validate_v1_execution.py
python3 tools/validate_v1_evidence.py docs/evidence/v1/P02-conformance/verify.json
git diff --check
```

P02 receives exactly one implementation pass and one Sol review. Any unresolved finding is
assigned to a later owning packet and must be closed by P32. Stop and escalate only for a request
to patch Control, loosen a refusal, pass observed outcomes into routing, use unpinned tools, or
expand into unrelated runtime/interface work. This packet contains no approval assertion.
