# Security

## Threat model

`/watch` feeds an AI agent with text and images derived from videos that
strangers uploaded. We treat every video-derived string — transcript,
description, title, uploader name, chapter titles — as attacker-controlled and
neutralize it before the model reads it (`sanitize_for_report` in
`skills/watch/scripts/download.py`): trust-boundary markers are matched loosely
and defused, code-fence openers are defanged, exotic line terminators are
normalized. The adversarial suite is `tests/test_report_sanitization.py`, and a
public fixture anyone can run is
[docs/does-your-video-skill-pass-this.md](docs/does-your-video-skill-pass-this.md).

Also in scope and hardened separately: subprocess argv injection (yt-dlp/ffmpeg
inputs), SSRF via the local transcription server (all 3xx redirects refused),
and audio egress (cloud transcription requires both a key and
`--allow-remote-transcription`; local backends run first).

Out of scope: malicious media containers (we rely on ffmpeg's own hardening),
and a machine that is already compromised.

## Reporting

Found a bypass — a payload that survives sanitization and reads as instructions,
markers, or report structure? Please open a GitHub issue with the payload and
the observed output, or use GitHub's private vulnerability reporting on this
repo if it's sensitive. We ship our own bug reports in the CHANGELOG (see the
boundary-escape fix history), and we'll credit you.
