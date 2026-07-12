# Mechanism disposition and provenance

`ship` means required for v1.0 only after its named gate. It does not mean that a planned
mechanism already exists in the current runtime. `evaluate-only` produces evidence but no default
runtime promise. `defer` is outside v1.0. `exclude` must not ship.

The current derivative runtime contains inherited upstream code and independently authored
`abe238/claude-video-plus` changes. No source code from the concept-reference forks below was
copied. Revision and license identify the exact public design reference inspected; implementation
in this repository was written independently and the linked author/repository is credited publicly.

| Mechanism | Disposition | Origin | Use in this repository | License/credit action |
| --- | --- | --- | --- | --- |
| upstream caption-first, FFmpeg/yt-dlp, fail-open skill | ship; inherited now | [Brad Bonanno / `bradautomates/claude-video@83da59f`](https://github.com/bradautomates/claude-video/tree/83da59fa78c3eee9e20f515fe75c438bb5166efd) | inherited code/history | MIT; retain `LICENSE`, Brad Bonanno, `@bradautomates`, repo link, and history |
| evidence compiler and derivative packaging | ship; derivative now | [Abe Diaz / `abe238/claude-video-plus`](https://github.com/abe238/claude-video-plus) | independently authored derivative changes | MIT; separate derivative claims from upstream authorship |
| SABR/client retry and cookie resilience concept | implemented; release gate pending | [`taeloautomates/claude-video@0d35812`](https://github.com/taeloautomates/claude-video/tree/0d35812ac8776de246ae2a6eb94d0a80299f1470) | independently implemented bounded default-first recovery | MIT reference; no code copied; user/repo credited in README/page |
| classified retry, range ASR, resume/cache, OCR ideas | implemented except OCR remains evaluate-only | [`thedirektor/claude-video@6d1e133`](https://github.com/thedirektor/claude-video/tree/6d1e1337497ca1758609d96cefb1d52537b26d47) | independently implemented bounded retry/range/resume concepts | MIT reference; no code copied; user/repo credited |
| caption coverage and Whisper reliability | implemented; release gate pending | [`RadoslavSheytanov/claude-video@c394aa1`](https://github.com/RadoslavSheytanov/claude-video/tree/c394aa1e35bc1528543565d574e58afe4fdcf729) | independently implemented ordered captions and bounded cloud behavior | MIT reference; no code copied; user/repo credited |
| VTT/SRT sidecar-first transcription | implemented | [`Tigertycoon/claude-video@bc02a01`](https://github.com/Tigertycoon/claude-video/tree/bc02a0179d9f1571caee2b8cd079fb7f08ae7a7b), [`manojbadam/claude-video@560ae96`](https://github.com/manojbadam/claude-video/tree/560ae963b7c31d2d709a2612a4a7c9d3795bbf54) | independently implemented exact-basename sidecar Adapter | both MIT references; no code copied; both users/repos credited |
| Fathom private-call source | defer | [`CJNA/claude-video`](https://github.com/CJNA/claude-video) | no v1 runtime or evaluation; reopen with owner use case | no code copied; retain design credit |
| local transcription and portable bundles | implemented; release gate pending | [`sciencemj/claude-video-local@1f6ddfb`](https://github.com/sciencemj/claude-video-local/tree/1f6ddfb9a9fb3a250022c3d534d5da0e99b08a54) | independently implemented normalized local Adapter and bundle architecture; slide PDF deferred | MIT reference; no code copied; user/repo credited |
| local whisper.cpp backend | defer | [`troyshelton/claude-video`](https://github.com/troyshelton/claude-video) | generic loopback server supports external deployments; no direct Adapter/install | no code copied; name if mechanism later ships |
| faster-whisper and rolling-caption dedup | implemented compatibility/normalization | [`jsstn/claude-video@465b385`](https://github.com/jsstn/claude-video/tree/465b3852732c5f48bed4b885cea8d55761684318) | independently implemented generic loopback endpoint and normalization | MIT reference; no code copied; user/repo credited |
| silence-aware chunks and JSON diagnostics | implemented | [`joweiser/claude-video@17f45aa`](https://github.com/joweiser/claude-video/tree/17f45aa3433c1b25f991a899c7ffbeb2d92fc2dc) | independently implemented silence-aware planning and diagnostics | MIT reference; no code copied; user/repo credited |
| focused transcription and bounded retry/cache | implemented | [`JoseBallestas/claude-video@dd86f9a`](https://github.com/JoseBallestas/claude-video/tree/dd86f9acd1b767c3dc7b13597987d712108432d3) | independently implemented range extraction and bounded receipts | MIT reference; no code copied; user/repo credited |
| pluggable local-first STT and resume | implemented; diarization deferred | [`danielfrey63/claude-video@07bf5fb`](https://github.com/danielfrey63/claude-video/tree/07bf5fb4eb3c3198dd68c5d033173513f0f96f41) | architectural reference for independently written Adapter pipeline | MIT reference; no code copied; user/repo credited |
| YAP local transcription | implemented optional Adapter | [`finnvoor/yap@90d7654`](https://github.com/finnvoor/yap/tree/90d76546ce9b6085759b8dd19465d1556766543e) | detected, never automatically installed | CC0-1.0 reference; no code copied; user/repo credited |
| faster-whisper HTTP at loopback `:8082` | implemented compatible endpoint | [`SYSTRAN/faster-whisper@ed9a06c`](https://github.com/SYSTRAN/faster-whisper/tree/ed9a06cd89a93e47838f564998a6c09b655d7f43) | generic OpenAI-compatible Adapter, no bundled model | MIT reference; no code copied or automatic install; project credited |
| OCR/frame-text semantic retrieval | evaluate-only | cited forks/research | no runtime promotion without separate gate and owner approval | publish negative/positive ablation and sources |
| OpenCV/PySceneDetect | exclude | OpenCV, PySceneDetect, [`DanielZYoffe/claude-video-lite`](https://github.com/DanielZYoffe/claude-video-lite) | negative development ablation; no code/install/config | no code copied; retain rejection evidence; do not imply incorporation |
| Cascade/Parable execution pattern | ship process; documentation only | [Miguel Rios / `miguelrios/unc-skills`](https://github.com/miguelrios/unc-skills) | inspiration for bounded loops and independent author/reviewer roles; no copied runtime code | MIT source; name Miguel Rios/user/repo |

Before a packet reuses code rather than a concept, record exact source URL, revision, files,
license, modifications, and notices in this table and release notes. Attribution tests verify
every shipped origin's required user/repository names and links in public material.
