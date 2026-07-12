# Mechanism disposition and provenance

`ship` means required for v1.0 only after its named gate. It does not mean that a planned
mechanism already exists in the current runtime. `evaluate-only` produces evidence but no default
runtime promise. `defer` is outside v1.0. `exclude` must not ship.

The current derivative runtime contains inherited upstream code and independently authored
`abe238/claude-video-plus` changes. No source code from the concept-reference forks below has been
copied into the runtime as of packet P04. Before that changes, the implementing packet must add the
exact source URL, revision, files, license, modifications, and notices here and in release notes.

| Mechanism | Disposition | Origin | Use in this repository | License/credit action |
| --- | --- | --- | --- | --- |
| upstream caption-first, FFmpeg/yt-dlp, fail-open skill | ship; inherited now | [Brad Bonanno / `bradautomates/claude-video@83da59f`](https://github.com/bradautomates/claude-video/tree/83da59fa78c3eee9e20f515fe75c438bb5166efd) | inherited code/history | MIT; retain `LICENSE`, Brad Bonanno, `@bradautomates`, repo link, and history |
| evidence compiler and derivative packaging | ship; derivative now | [Abe Diaz / `abe238/claude-video-plus`](https://github.com/abe238/claude-video-plus) | independently authored derivative changes | MIT; separate derivative claims from upstream authorship |
| SABR/client retry and cookie resilience concept | ship after gate; planned | [`taeloautomates/claude-video`](https://github.com/taeloautomates/claude-video) | adapt concept; do not copy `18/` ordering | no code copied; verify source license before reuse; name user/repo |
| classified retry, range ASR, resume/cache, OCR ideas | ship after gates except OCR evaluate-only; planned | [`thedirektor/claude-video`](https://github.com/thedirektor/claude-video) | independently adapt bounded mechanisms | no code copied; verify source license before reuse; name user/repo |
| caption coverage and Whisper reliability | ship after gate; planned | [`RadoslavSheytanov/claude-video`](https://github.com/RadoslavSheytanov/claude-video) | adapt behavior and independently authored tests | no code copied; verify source license before reuse; name user/repo |
| VTT/SRT sidecar-first transcription | ship after gate; planned | [`Tigertycoon/claude-video`](https://github.com/Tigertycoon/claude-video), [`manojbadam/claude-video`](https://github.com/manojbadam/claude-video) | independently implement | no code copied; verify source licenses before reuse; name both users/repos |
| Fathom private-call source | defer | [`CJNA/claude-video`](https://github.com/CJNA/claude-video) | no v1 runtime or evaluation; reopen with owner use case | no code copied; retain design credit |
| local transcription and portable bundles | ship after gates; planned | [`sciencemj/claude-video-local`](https://github.com/sciencemj/claude-video-local) | adapt architecture; slide PDF deferred | no code copied; verify source license before reuse; name user/repo |
| local whisper.cpp backend | defer | [`troyshelton/claude-video`](https://github.com/troyshelton/claude-video) | generic loopback server supports external deployments; no direct Adapter/install | no code copied; name if mechanism later ships |
| faster-whisper and rolling-caption dedup | ship after gates; planned | [`jsstn/claude-video`](https://github.com/jsstn/claude-video) | generic loopback endpoint; caption normalization packet | no code copied; verify source license before reuse; name user/repo and faster-whisper maintainers |
| silence-aware chunks and JSON diagnostics | ship after gate; planned | [`joweiser/claude-video`](https://github.com/joweiser/claude-video) | independently adapt | no code copied; verify source license before reuse; name user/repo |
| focused transcription and bounded retry/cache | ship after gate; planned | [`JoseBallestas/claude-video`](https://github.com/JoseBallestas/claude-video) | independently adapt | no code copied; verify source license before reuse; name user/repo |
| pluggable local-first STT and resume | ship after gates; planned; diarization defer | [`danielfrey63/claude-video`](https://github.com/danielfrey63/claude-video) | architectural reference | no code copied; verify source license before reuse; name user/repo |
| YAP local transcription | ship optional after gate; planned | [`finnvoor/yap`](https://github.com/finnvoor/yap) | detected, never automatically installed | no code copied; record exact license and revision before Adapter ships |
| faster-whisper HTTP at loopback `:8082` | ship compatible endpoint | faster-whisper/server maintainers | generic OpenAI-compatible Adapter, no bundled model | name maintainers; no automatic install |
| OCR/frame-text semantic retrieval | evaluate-only | cited forks/research | no runtime promotion without separate gate and owner approval | publish negative/positive ablation and sources |
| OpenCV/PySceneDetect | exclude | OpenCV, PySceneDetect, [`DanielZYoffe/claude-video-lite`](https://github.com/DanielZYoffe/claude-video-lite) | negative development ablation; no code/install/config | no code copied; retain rejection evidence; do not imply incorporation |
| Cascade/Parable execution pattern | ship process; documentation only | [Miguel Rios / `miguelrios/unc-skills`](https://github.com/miguelrios/unc-skills) | inspiration for bounded loops and independent author/reviewer roles; no copied runtime code | MIT source; name Miguel Rios/user/repo |

Before a packet reuses code rather than a concept, record source URL, exact revision, files,
license, modifications, and notices in this table and release notes. Attribution tests verify
every shipped origin's required user/repository names and links in public material.
