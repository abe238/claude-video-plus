# Runtime and product contracts

## Normalized result states

Every deep Interface returns one state plus structured attempts, non-secret provenance,
warnings, and fallback reason:

| State | Meaning | Process behavior |
| --- | --- | --- |
| `success` | Requested evidence is complete | exit 0 |
| `degraded` | A declared fallback completed the request | exit 0; one actionable warning in manifest/report |
| `partial` | Useful evidence exists but a requested modality/range is incomplete | exit 0 only when the skill can answer honestly; manifest marks missing obligations |
| `unavailable` | This Adapter cannot run in this environment | continue ordered fallback without user noise when a later Adapter succeeds |
| `fatal` | Invalid input/configuration or no safe analyzable evidence after exhaustion | nonzero with stable failure code and no fabricated answer |

Stable process exits: `0` usable result, `2` invalid invocation/configuration, `3` source or
required evidence unavailable after fallback exhaustion, `4` integrity/privacy refusal, `5`
internal invariant failure. Adapter-specific provider errors are classified before mapping.

## Acquisition taxonomy

Retry only `sabr_client`, transient `http_403`, `http_429`, transient network timeout, or
format-unavailable under the bounded policy. Do not retry invalid URL/path, explicit login,
region lock, private/deleted source, unsupported extractor, cookie-profile validation failure,
or integrity refusal. Preserve the default attempt first, then one configured player client at a
time, then itag 18 as final format fallback. Each attempt is recorded without cookies, headers,
signed query strings, or local profile paths.

## Transcription precedence

The default order is native captions, same-basename sidecar, configured loopback HTTP, YAP,
Groq, OpenAI, then explicit no-transcript result. A successful earlier Adapter prevents every
later upload/call. Invalid explicit Adapter selection is exit 2. An unavailable optional Adapter
falls through; a partial transcript falls through only when its completeness contract fails.
Retries are bounded per Adapter and never repeat completed chunks.

## Evidence state

Checksum/schema/permission mismatch makes a cache entry a recorded miss, never trusted input.
Interrupted or concurrent writes use owner-only temporary files and atomic rename. Exhausted
storage or unsafe permissions disable reuse and continue uncached when safe. Purge distinguishes
configuration, derived evidence, and optional runtime state.

## User-visible surface

The product surface is `/watch VIDEO [QUESTION] [documented options]`. `watch.py` is an internal
portable runtime used by every host. Every user option must map consistently to:

1. slash-command text parsed by the host agent;
2. a quoted internal script argument or documented environment/config value;
3. validation, precedence, and machine-readable diagnostics.

Precedence is explicit invocation > project configuration > user configuration > default.
Unknown options or invalid values fail before network/media work. Machine-readable JSON is an
internal/automation output, not a separate competing CLI product. Unsupported host capabilities
produce a declared fallback or stable error rather than silently changing behavior.

## Privacy and retention matrix

| Data class | Default persistence | Identity/log rule | Remote transmission |
| --- | --- | --- | --- |
| public URL metadata | bounded manifest/cache | strip query/fragment; hash canonical identity | only source acquisition |
| authenticated/signed URL | none beyond active task | redact query, headers, cookies, profile/path | only explicitly enabled acquisition |
| local source path/media | no copied media | store salted content identity, never absolute path in portable bundle | never without explicit Adapter consent |
| transcript/sidecar text | active task only; reusable cache opt-in | owner-only, TTL/size bounded | only explicitly enabled remote Adapter |
| OCR text | active task only; cache opt-in | same as transcript | only explicitly enabled remote Adapter |
| embeddings/index | local opt-in cache | model/version + hashed source identity | remote embedding requires explicit configuration |
| extracted frames/crops | active task only | portable bundle only by explicit export | remote reader only as required by enabled host workflow |
| manifest/receipts | bounded local derived state | redact secrets, URLs, paths, headers | never automatically |
| logs | minimal bounded diagnostics | no transcript/media/header/query-secret content | never automatically |

Derived state defaults to `~/.cache/watch/` with owner-only permissions, bounded size and TTL;
configuration remains under `~/.config/watch/`. `purge` removes derived state, `uninstall`
documents separate configuration removal, and portable export includes only explicitly selected
evidence with relative paths and checksums. Artifact scans must plant and reject cookies, API
keys, signed URL parameters, authorization headers, absolute private paths, and unrequested text.

## Incomplete-feature gate

New Adapters, scorers, caches, semantic policies, and retries remain unreachable from default
behavior until focused tests, full tests, compatibility conformance, install smoke tests,
ordinary-path latency, failure fallback, privacy, and packet-specific measurement gates pass.
Experimental paths require an explicit non-default capability flag and an `experimental` result
marker. Removal of that marker is a separately reviewed packet.
