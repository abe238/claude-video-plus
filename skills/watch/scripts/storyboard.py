#!/usr/bin/env python3
"""YouTube storyboard frame fallback.

When a YouTube URL is bot-gated for MEDIA but not for metadata (the "partial
gate": ``yt-dlp -J`` and captions succeed, the googlevideo media download 403s),
the low-res storyboard mosaics still serve from ``i.ytimg.com`` — verified from a
datacenter IP, and the tile URLs are not IP-bound. This module turns those
mosaics into fallback frames so a bot-gated run degrades to "captions + coarse
frames" instead of crashing.

Approach (deliberately NOT the mhtml route): the storyboard geometry is already
structured in the ``video.info.json`` we fetch — each ``sb*`` format carries
``columns``/``rows``/``width``/``height`` and a ``fragments`` list of
``{url, duration}`` mosaics. We read that, HTTP GET the bounded mosaic images,
and ffmpeg-crop the tiles. No binary container parsing, no magic-byte sniffing:
the only untrusted surface is (a) image bytes, decoded by ffmpeg exactly like
every other video frame, and (b) the integer geometry, bounded here.

Every value in info.json is attacker-controllable, so the whole extraction is
wrapped fail-open: any malformed input yields an empty frame list, never a raise
(the run keeps whatever transcript it already has).

These frames are LOW-RES (typically 320x180): fine on-screen text may be
unreadable. The caller labels them as a degraded fallback in the report.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from frames import _even_indices, _scale_filter, dedupe_perceptual  # noqa: E402

# Bounds on untrusted values from info.json (a hostile/oversized storyboard
# description must never explode fetches, ffmpeg calls, or disk).
MAX_MOSAICS = 300          # fragment (mosaic image) count
MAX_TILES_PER_MOSAIC = 400  # columns * rows
MAX_TILE_DIM = 1000        # per-tile width/height in px
MAX_MOSAIC_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
_FETCH_TIMEOUT = 20
_ALLOWED_HOST_SUFFIX = ".ytimg.com"  # storyboards live here; refuse anywhere else
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"


def _allowed_url(url: object) -> bool:
    """https on an i.ytimg.com host only — an info.json tile URL is untrusted,
    so it must not be able to point the fetch at an arbitrary host."""
    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "ytimg.com" or host.endswith(_ALLOWED_HOST_SUFFIX))


def _http_fetch(url: str, limit: int = MAX_MOSAIC_BYTES) -> bytes:
    """Fetch at most ``limit`` bytes; raise if the body would exceed it. Host
    is validated by the caller (``_allowed_url``) before we get here."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310 (https+host checked)
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"mosaic exceeds {limit} bytes")
    return data


def _pick_storyboard(info: object) -> dict | None:
    """Highest-resolution storyboard format with usable, in-bounds geometry.
    Tolerates any malformed shape (non-dict info/format/fragment) by skipping."""
    formats = info.get("formats") if isinstance(info, dict) else None
    best = None
    best_area = 0
    for fmt in (formats or []):
        if not isinstance(fmt, dict):
            continue
        note = str(fmt.get("format_note") or "")
        fid = str(fmt.get("format_id") or "")
        if note != "storyboard" and not fid.startswith("sb"):
            continue
        try:
            cols = int(fmt.get("columns") or 0)
            rows = int(fmt.get("rows") or 0)
            tw = int(fmt.get("width") or 0)
            th = int(fmt.get("height") or 0)
        except (TypeError, ValueError):
            continue
        frags = fmt.get("fragments")
        if not isinstance(frags, list) or not frags:
            continue
        if not (1 <= cols and 1 <= rows and cols * rows <= MAX_TILES_PER_MOSAIC):
            continue
        if not (0 < tw <= MAX_TILE_DIM and 0 < th <= MAX_TILE_DIM):
            continue
        area = tw * th
        if area > best_area:
            best, best_area = fmt, area
    return best


def _frag_duration(frag: object) -> float:
    """Guarded per-mosaic duration: non-dict / non-finite / negative -> 0.0."""
    if not isinstance(frag, dict):
        return 0.0
    d = frag.get("duration")
    if isinstance(d, (int, float)) and math.isfinite(d) and d >= 0:
        return float(d)
    return 0.0


def _plan_tiles(fmt: dict, lo: float, hi: float) -> list[tuple[int, float]]:
    """Return ``(global_tile_index, timestamp)`` for every real tile whose
    timestamp lands in ``[lo, hi]``.

    Storyboard thumbnails are evenly spaced: yt-dlp gives every full mosaic the
    same ``fragment_duration`` and only the LAST fragment a shorter remainder,
    so tile spacing is constant at ``fragment_duration / (cols*rows)``. Tiles
    whose timestamp runs past the real total (padding in the half-empty last
    mosaic) are dropped rather than mislabeled. The global index is preserved so
    the caller can map it back to ``(mosaic, tile-in-mosaic)``.
    """
    cols, rows = int(fmt["columns"]), int(fmt["rows"])
    per = cols * rows
    frags = fmt["fragments"][:MAX_MOSAICS]
    durs = [_frag_duration(f) for f in frags]
    total_span = sum(durs)
    # Constant tile interval from the first (full) mosaic; fall back to spreading
    # the total span across all tiles if the first duration is unusable.
    if durs and durs[0] > 0:
        interval = durs[0] / per
    elif total_span > 0:
        interval = total_span / (len(frags) * per)
    else:
        return []
    tiles: list[tuple[int, float]] = []
    for gi in range(len(frags) * per):
        ts = (gi + 0.5) * interval
        if total_span and ts >= total_span:
            continue  # padding tile past the end of the video
        if lo <= ts <= hi:
            tiles.append((gi, ts))
    return tiles


def _extract(info, out_dir, max_frames, resolution, dedup, fetch, lo, hi, meta):
    fmt = _pick_storyboard(info)
    if fmt is None:
        meta["note"] = "no-storyboard-format"
        return []

    cols = int(fmt["columns"])
    per = cols * int(fmt["rows"])
    tw, th = int(fmt["width"]), int(fmt["height"])
    frags = fmt["fragments"][:MAX_MOSAICS]

    tiles = _plan_tiles(fmt, lo, hi)
    meta["candidate_count"] = len(tiles)
    if not tiles:
        meta["note"] = "no-tiles-in-range"
        return []

    # Even-sample the tiles we want BEFORE fetching or cropping anything, then
    # fetch only the mosaics that own a selected tile (bound the work; don't
    # crop all N then trim).
    selected = [tiles[i] for i in _even_indices(len(tiles), max_frames)]
    needed_mosaics = sorted({gi // per for gi, _ in selected})

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("sb_*.jpg"):
        stale.unlink()

    mosaic_paths: dict[int, Path] = {}
    total = 0
    for m in needed_mosaics:
        if m >= len(frags) or not isinstance(frags[m], dict):
            continue
        url = frags[m].get("url")
        if not _allowed_url(url):
            print(f"[watch] storyboard mosaic {m} URL rejected (host/scheme)", file=sys.stderr)
            continue
        try:
            data = fetch(url)
        except Exception as exc:  # fail-open per mosaic
            print(f"[watch] storyboard mosaic {m} fetch failed: {type(exc).__name__}", file=sys.stderr)
            continue
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            print("[watch] storyboard total-bytes cap hit; stopping fetch", file=sys.stderr)
            break
        mp = out_dir / f"_mosaic_{m}.img"
        mp.write_bytes(data)
        mosaic_paths[m] = mp

    frames: list[dict] = []
    try:
        for gi, ts in selected:
            m = gi // per
            mp = mosaic_paths.get(m)
            if mp is None:
                continue
            r, c = divmod(gi % per, cols)
            x, y = c * tw, r * th
            path = out_dir / f"sb_{len(frames):04d}.jpg"
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(mp),
                "-vf", f"crop={tw}:{th}:{x}:{y},{_scale_filter(resolution)}",
                "-frames:v", "1", "-q:v", "4", str(path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode == 0 and path.exists():
                frames.append({
                    "index": len(frames),
                    "timestamp_seconds": round(ts, 2),
                    "path": str(path),
                    "reason": "storyboard",
                })
    finally:
        for mp in mosaic_paths.values():
            try:
                mp.unlink()
            except OSError:
                pass

    if dedup and len(frames) > 1:
        frames, dropped = dedupe_perceptual(frames)
        for i, f in enumerate(frames):
            f["index"] = i
        meta["deduped_count"] = dropped
    return frames


def extract_storyboard_frames(
    info: dict,
    out_dir: Path,
    max_frames: int = 60,
    resolution: int = 512,
    dedup: bool = True,
    fetch: Callable[[str], bytes] = _http_fetch,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> tuple[list[dict], dict]:
    """Fail-open storyboard frame extraction. Returns ``(frames, meta)``; an
    empty list on any shortfall or malformed input — NEVER raises, so it can sit
    on a fallback path without bricking the run."""
    meta = {"engine": "storyboard", "candidate_count": 0, "selected_count": 0,
            "fallback": True, "note": ""}
    if shutil.which("ffmpeg") is None:
        meta["note"] = "ffmpeg-missing"
        return [], meta
    lo = start_seconds if start_seconds is not None else 0.0
    hi = end_seconds if end_seconds is not None else float("inf")
    try:
        frames = _extract(info, out_dir, max_frames, resolution, dedup, fetch, lo, hi, meta)
    except Exception as exc:  # untrusted metadata: fail open, never crash the run
        print(f"[watch] storyboard extraction error ({type(exc).__name__}); skipping", file=sys.stderr)
        frames = []
        meta["note"] = f"error:{type(exc).__name__}"
    meta["selected_count"] = len(frames)
    if not frames and not meta["note"]:
        meta["note"] = "all-fetches-failed"
    return frames, meta


if __name__ == "__main__":  # ponytail: geometry/plan self-check, no network
    fmt = {"format_id": "sb0", "format_note": "storyboard", "columns": 3, "rows": 3,
           "width": 320, "height": 180,
           "fragments": [{"url": "https://i.ytimg.com/x.jpg", "duration": 90.0},
                         {"url": "https://i.ytimg.com/y.jpg", "duration": 45.0}]}
    assert _pick_storyboard({"formats": [fmt]}) is fmt
    tiles = _plan_tiles(fmt, 0.0, float("inf"))
    # mosaic0 full (9 tiles, gi 0-8); mosaic1 remainder 45s at interval 10s -> real
    # tiles at 95/105/115/125 (gi 9-12), the gi=13 tile lands at 135.0 == total and
    # is dropped as padding. So 13 real tiles, no mislabeled blank at the end.
    assert [gi for gi, _ in tiles] == list(range(0, 13)), [gi for gi, _ in tiles]
    ts = [t for _, t in tiles]
    assert ts == sorted(ts) and ts[0] == 5.0 and ts[-1] < 135.0
    # focus window filter
    win = _plan_tiles(fmt, 20.0, 40.0)
    assert win and all(20.0 <= t <= 40.0 for _, t in win)
    # bounds: hostile geometry rejected
    assert _pick_storyboard({"formats": [{"format_id": "sb0", "columns": 99999,
                                          "rows": 99999, "width": 320, "height": 180,
                                          "fragments": [{"url": "x"}]}]}) is None
    assert _pick_storyboard({"formats": [{"format_id": "sb0", "columns": 3, "rows": 3,
                                          "width": 99999, "height": 180,
                                          "fragments": [{"url": "x"}]}]}) is None
    assert _pick_storyboard({"formats": []}) is None
    # non-dict shapes tolerated (no raise)
    assert _pick_storyboard(["not", "a", "dict"]) is None
    assert _pick_storyboard({"formats": ["x"]}) is None
    # non-finite duration does not produce inf timestamps
    bad = dict(fmt, fragments=[{"url": "https://i.ytimg.com/x.jpg", "duration": float("inf")}])
    assert _plan_tiles(bad, 0.0, float("inf")) == []
    # host guard
    assert _allowed_url("https://i.ytimg.com/sb/x/M0.jpg")
    assert not _allowed_url("http://i.ytimg.com/sb/x/M0.jpg")   # not https
    assert not _allowed_url("https://evil.example.com/x.jpg")   # wrong host
    assert not _allowed_url("https://i.ytimg.com.evil.com/x")   # suffix spoof
    assert not _allowed_url(None)
    print("storyboard self-check OK")
