# v1.0 support and installation matrix

## Support tiers

Tier A is release-blocking. Tier B is compatibility-tested where runners are available and may
not be advertised as fully supported without a passing artifact. “50+ hosts” describes Agent
Skills CLI discovery breadth, not 50 independently certified runtimes.

| Tier | OS/architecture | Python | Host/install surface | Required system tools |
| --- | --- | --- | --- | --- |
| A | macOS 14+ arm64 | 3.11, 3.12, 3.14 | Claude Code plugin; Codex/Agent Skills global and project; manual symlink | FFmpeg/ffprobe, yt-dlp |
| A | Ubuntu 22.04/24.04 x86_64 | 3.11, 3.12 | Agent Skills project install; manual symlink | FFmpeg/ffprobe, yt-dlp |
| A | clean claude.ai code-execution environment | bundled Python | released `watch.skill` upload | host-provided execution plus documented binaries |
| B | Windows 11 x86_64 | 3.11, 3.12 | Agent Skills project install/manual copy | ffmpeg/ffprobe, yt-dlp; `python` command |
| B | other Agent Skills hosts | supported host Python | `npx skills add` discovery | same runtime contract |

## Required isolated procedures

For every Tier A row, store command, environment, exit, filesystem inventory, and cleanup proof:

1. fresh install from an empty temporary home/project;
2. first invocation and successful silent repeat preflight;
3. update from the prior maintenance release;
4. rollback to the prior release;
5. project and global invocation/path resolution;
6. derived-state status, verify, and purge;
7. uninstall with configuration retained, then explicit configuration removal;
8. reinstall after uninstall;
9. offline/missing-tool behavior;
10. release artifact contents, checksum, and size.

Claude Code tests marketplace/plugin layout. Agent Skills tests global, project, symlink, and
`--copy` layouts. claude.ai tests exactly one `SKILL.md`, relative script resolution, and the
documented capability requirement. Windows uses `python`, path spaces, and copy mode where
symlinks are unavailable.

## Preflight benchmark

On each Tier A machine, record CPU/model, OS, Python, cold/warm state, and dependency lookup
state. Run 30 warm successful `setup.py --check` invocations. Require empty stdout/stderr, zero
exit, and p95 below 100 ms. Apply the jitter definition in `MEASUREMENT.md`; do not substitute a
single fast run.

## Release evidence

An environment is supported only when the release commit has a passing install result conforming
to `EVIDENCE-SCHEMAS.md`. Missing runners remain explicitly unverified. Release documentation
must separate supported, compatibility-tested, and discoverable-only hosts.
