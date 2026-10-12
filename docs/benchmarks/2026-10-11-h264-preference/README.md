# H.264 (avc1) preference in the format ladder

Idea from thomasdupkavich/claude-video (their code was not run). Their claim: for the same video, H.264 is smaller and faster (21 MB / 5.5 s vs 52 MB / 13.5 s). Measured here with plain yt-dlp 2026-10-11, Apple M5 Pro, one run per cell except IiZ5HRaeX4s (2 to 3 runs, stable).

## Result: size claim REFUTED, decode claim CONFIRMED

At 720p, H.264 is the LARGEST of the 720p candidates on both videos tested.

| Video | avc1 720p | vp9 720p | av01 720p |
|---|---|---|---|
| IiZ5HRaeX4s (screencast/talk, 824 s) | 51.4 MB | 54.1 MB | 41.3 MB |
| dQw4w9WgXcQ (music video, 213 s) | 26.5 MB | 17.7 MB | 17.6 MB |
| jNQXAC9IVRw (19 s, max 240p) | 0.43 MB (240p) | 0.29 MB | 0.22 MB |

Actual downloads. "current" = existing ladder (yt-dlp default sort picked AV1); "avc1" = avc1 rungs first.

| Video | Ladder | Codec | Size | Download | ffmpeg full decode |
|---|---|---|---|---|---|
| dQw4w9WgXcQ | current | av1 720p | 21.0 MB | 2.2 s | 1.7 s |
| dQw4w9WgXcQ | avc1 | h264 720p | 29.9 MB | 2.5 s | 0.6 s |
| IiZ5HRaeX4s | current | av1 720p | 55.5 MB | 3.6 / 2.7 / 2.7 s | 7.6 / 7.5 / 7.7 s |
| IiZ5HRaeX4s | avc1 | h264 720p | 65.7 MB | 6.8 / 5.8 s | 2.3 / 2.4 s |

Sum (download + decode): IiZ5HRaeX4s 10.4 s vs 8.2 s; dQw4w9WgXcQ 3.9 s vs 3.1 s. H.264 wins wall time by about 20 percent, but only through decode (about 3x faster); it costs 18 to 42 percent more bytes and was not faster to download. On a slow link the extra bytes could erase the win; on slow CPUs the decode gap grows.

## Decision

Adopted, with the honest framing "faster decode, larger file", not "smaller". The two avc1 rungs go first; all prior rungs follow unchanged, so sources without avc1 (non-YouTube, HLS without codec tags) fall through exactly as before. Height bound unchanged. Caveat: an opt-in `WATCH_MAX_FILESIZE` cap can trip slightly more often.

## Live check

`watch.py https://www.youtube.com/watch?v=dQw4w9WgXcQ` end to end: downloaded `video.mp4` is h264, 720p (ffprobe), frames and transcript produced.
