# Mechanism disposition and provenance

`ship` means required for v1.0 after its gate. `evaluate-only` produces evidence but no default
runtime promise. `defer` is outside v1.0. `exclude` must not ship.

| Mechanism | Disposition | Origin | Use in this repository | License/credit action |
| --- | --- | --- | --- | --- |
| upstream caption-first, FFmpeg/yt-dlp, fail-open skill | ship | `bradautomates/claude-video@83da59f` | inherited code/history | retain MIT, Brad Bonanno, `@bradautomates`, repo link |
| SABR/client retry and cookie resilience concept | ship | `taeloautomates/claude-video` | adapt concept; do not copy `18/` ordering | name user/repo; inspect source license before code reuse |
| classified retry, range ASR, resume/cache, OCR ideas | ship except OCR evaluate-only | `thedirektor/claude-video` | independently adapt bounded mechanisms | name user/repo; record any copied commit/files |
| caption coverage and Whisper reliability | ship | `RadoslavSheytanov/claude-video` | adapt tests/behavior | name user/repo |
| VTT/SRT sidecar-first transcription | ship | `Tigertycoon/claude-video`, `manojbadam/claude-video` | independently implement | name both users/repos |
| Fathom private-call source | defer | `CJNA/claude-video` | no v1 runtime or evaluation; reopen with owner use case | retain design credit |
| local transcription and portable bundles | ship | `sciencemj/claude-video-local` | adapt architecture; slide PDF deferred | name user/repo |
| local whisper.cpp backend | defer | `troyshelton/claude-video` | generic loopback server supports external deployments; no direct Adapter/install | name if mechanism later ships |
| faster-whisper and rolling-caption dedup | ship | `jsstn/claude-video` | generic loopback endpoint; caption normalization packet | name user/repo and faster-whisper maintainers |
| silence-aware chunks and JSON diagnostics | ship | `joweiser/claude-video` | independently adapt | name user/repo |
| focused transcription and bounded retry/cache | ship | `JoseBallestas/claude-video` | independently adapt | name user/repo |
| pluggable local-first STT and resume | ship; diarization defer | `danielfrey63/claude-video` | architectural reference | name user/repo |
| YAP local transcription | ship optional | `finnvoor/yap` | detected, never automatically installed | name user/repo/license |
| faster-whisper HTTP at loopback `:8082` | ship compatible endpoint | faster-whisper/server maintainers | generic OpenAI-compatible Adapter, no bundled model | name maintainers; no automatic install |
| OCR/frame-text semantic retrieval | evaluate-only | cited forks/research | no runtime promotion without separate gate and owner approval | publish negative/positive ablation and sources |
| OpenCV/PySceneDetect | exclude | OpenCV, PySceneDetect, `DanielZYoffe/claude-video-lite` | negative development ablation; no code/install/config | retain rejection evidence; do not imply incorporation |
| Cascade/Parable execution pattern | ship process | `miguelrios/unc-skills` | inspiration for bounded loops and independent author/reviewer roles; no copied runtime code | name Miguel Rios/user/repo and MIT source |

Before a packet reuses code rather than a concept, record source URL, exact revision, files,
license, modifications, and notices in this table and release notes. Attribution tests verify
every shipped origin's required user/repository names and links in public material.
