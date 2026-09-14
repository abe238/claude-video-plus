# /watch — failure modes and handling

Read this when a run fails, prints a warning, or returns less than expected.

## Failure modes

- **Setup preflight failed** → run `python3 "${SKILL_DIR}/scripts/setup.py"` (auto-installs ffmpeg/yt-dlp via brew on macOS, scaffolds a blank `.env`). Never request or handle a key; direct the user to configure it privately outside the agent.
- **No transcript available** → captions missing AND (no Whisper key OR Whisper API failed). Script prints a hint pointing to setup. Proceed frames-only and tell the user.
- **Long video warning printed** → acknowledge it in your answer. Offer to re-run focused on a specific section via `--start`/`--end` rather than a sparse full-video scan.
- **TikTok photo post (image slideshow)** → yt-dlp has no extractor for `/photo/` URLs (and returns only the soundtrack for the `/video/` spelling). If `gallery-dl` is on PATH the script fetches the slides itself and the report lists frames as `slide N` with no timeline: Read every slide and treat the caption (Title) plus on-slide text as the content. A yt-dlp `ERROR: Unsupported URL` on stderr above a successful report is expected here. If stderr says to install gallery-dl, tell the user (`brew install gallery-dl` or `pipx install gallery-dl`); it is never installed automatically. A slideshow transcript, if any, is Whisper on the soundtrack and is often background music or hallucinated lyrics: weight the slides and caption over it.
- **Download fails** → yt-dlp's error goes to stderr. If it's a login-required or region-locked video, tell the user plainly; do not keep retrying.
- **Whisper request fails** → the error is printed to stderr (likely: invalid key or rate limit). Audio over the API's 25 MB upload cap is split into chunks and transcribed automatically, so length alone won't fail it; if some chunks fail the transcript is partial and the dropped chunks are noted on stderr. The report will say "none available" only if every chunk fails. You can retry with `--whisper openai` if Groq failed (or vice versa).

