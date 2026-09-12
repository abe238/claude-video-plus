"""Storyboard fallback: geometry, bounds, fail-open, hostile inputs.

The premise (storyboard tiles serve from i.ytimg.com even from a datacenter IP,
so a partial YouTube bot-gate can degrade to storyboard frames instead of
crashing) was verified live 2026-09-12 (VPS 72.60.28.52: tile + control both
200, signature not IP-bound). These tests cover the parsing/cropping/bounds and
the fail-open contract against hostile info.json; no network — a fetch stub
supplies bytes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "watch" / "scripts"))

import storyboard  # noqa: E402

ffmpeg_only = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def _fmt(cols=3, rows=3, w=320, h=180, durations=(90.0, 90.0)):
    return {
        "format_id": "sb0", "format_note": "storyboard",
        "columns": cols, "rows": rows, "width": w, "height": h,
        "fragments": [{"url": f"https://i.ytimg.com/sb/x/M{i}.jpg", "duration": d}
                      for i, d in enumerate(durations)],
    }


def _mosaic_bytes(tmp_path: Path, w=960, h=540) -> bytes:
    """A real image the size of a cols*tile_w by rows*tile_h grid, via ffmpeg."""
    p = tmp_path / "mosaic.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=size={w}x{h}:duration=1:rate=1", "-frames:v", "1", str(p)],
        check=True,
    )
    return p.read_bytes()


def test_pick_storyboard_highest_res():
    info = {"formats": [_fmt(w=48, h=27), _fmt(w=320, h=180), {"format_id": "137"}]}
    picked = storyboard._pick_storyboard(info)
    assert picked is not None and picked["width"] == 320


def test_pick_storyboard_rejects_hostile_geometry():
    assert storyboard._pick_storyboard({"formats": [_fmt(cols=99999, rows=99999)]}) is None
    assert storyboard._pick_storyboard({"formats": [_fmt(w=99999)]}) is None
    assert storyboard._pick_storyboard({"formats": [{"format_id": "sb0", "columns": 3,
                                       "rows": 3, "width": 320, "height": 180,
                                       "fragments": []}]}) is None
    assert storyboard._pick_storyboard({"formats": []}) is None


def test_pick_storyboard_tolerates_non_dict_shapes():
    # blocker 1: malformed shapes must never raise, just skip
    assert storyboard._pick_storyboard(["not", "a", "dict"]) is None
    assert storyboard._pick_storyboard({"formats": ["x", 3, None]}) is None
    assert storyboard._pick_storyboard("garbage") is None


def test_plan_tiles_constant_interval_drops_padding():
    # concern 3: full mosaic (9 tiles) + a short remainder mosaic. Spacing stays
    # constant (10s); the tile that would land AT the total is padding and dropped.
    tiles = storyboard._plan_tiles(_fmt(durations=(90.0, 45.0)), 0.0, float("inf"))
    idx = [gi for gi, _ in tiles]
    ts = [t for _, t in tiles]
    assert idx == list(range(0, 13))          # 9 + 4 real tiles, no blank padding
    assert ts == sorted(ts)
    assert ts[0] == pytest.approx(5.0) and ts[-1] < 135.0


def test_plan_tiles_focus_window():
    # concern 6: only tiles inside [lo, hi] survive
    win = storyboard._plan_tiles(_fmt(durations=(90.0, 90.0)), 20.0, 40.0)
    assert win and all(20.0 <= t <= 40.0 for _, t in win)


def test_plan_tiles_non_finite_duration_yields_no_inf(monkeypatch):
    # blocker 2: Infinity/NaN durations must not produce inf/nan timestamps
    assert storyboard._plan_tiles(_fmt(durations=(float("inf"),)), 0.0, float("inf")) == []
    assert storyboard._plan_tiles(_fmt(durations=(float("nan"),)), 0.0, float("inf")) == []


@ffmpeg_only
def test_extract_produces_frames(tmp_path):
    data = _mosaic_bytes(tmp_path)
    info = {"formats": [_fmt(durations=(90.0, 90.0))]}
    frames, meta = storyboard.extract_storyboard_frames(
        info, tmp_path / "out", max_frames=6, fetch=lambda u: data)
    assert meta["engine"] == "storyboard" and meta["fallback"] is True
    assert 1 <= len(frames) <= 6
    for f in frames:
        assert f["reason"] == "storyboard"
        assert Path(f["path"]).exists() and Path(f["path"]).stat().st_size > 0
        assert 0 <= f["timestamp_seconds"] < 180  # finite, in-range
    assert not list((tmp_path / "out").glob("_mosaic_*"))  # temp mosaics cleaned up


@ffmpeg_only
def test_only_needed_mosaics_are_fetched(tmp_path):
    """Even-sampling happens BEFORE fetching: a 5-mosaic board sampled to 3
    frames must fetch only the 3 mosaics that own a selected tile, not all 5."""
    data = _mosaic_bytes(tmp_path)
    fetched = []

    def spy(url):
        fetched.append(url)
        return data

    info = {"formats": [_fmt(durations=(90.0,) * 5)]}  # 45 tiles
    storyboard.extract_storyboard_frames(info, tmp_path / "out", max_frames=3, fetch=spy)
    assert len(fetched) == 3   # even_indices(45,3) = [0,22,44] -> mosaics {0,2,4}


@ffmpeg_only
def test_extract_focus_window_limits_frames(tmp_path):
    data = _mosaic_bytes(tmp_path)
    info = {"formats": [_fmt(durations=(90.0, 90.0))]}
    frames, _ = storyboard.extract_storyboard_frames(
        info, tmp_path / "out", max_frames=20, fetch=lambda u: data,
        start_seconds=30.0, end_seconds=60.0)
    assert frames and all(30.0 <= f["timestamp_seconds"] <= 60.0 for f in frames)


@ffmpeg_only
def test_non_image_bytes_fail_open(tmp_path):
    info = {"formats": [_fmt(durations=(90.0,))]}
    frames, meta = storyboard.extract_storyboard_frames(
        info, tmp_path / "out", max_frames=4, fetch=lambda u: b"not an image at all")
    assert frames == []           # ffmpeg can't crop garbage -> no frames, no crash
    assert meta["selected_count"] == 0


@ffmpeg_only
def test_hostile_shapes_fail_open(tmp_path):
    # blocker 1: null fragment / array body must yield [], never AttributeError
    bad_frag = {"formats": [{"format_id": "sb0", "columns": 3, "rows": 3,
                             "width": 320, "height": 180, "fragments": [None, "x"]}]}
    frames, meta = storyboard.extract_storyboard_frames(bad_frag, tmp_path / "out")
    assert frames == []
    frames2, _ = storyboard.extract_storyboard_frames(["array", "body"], tmp_path / "out")
    assert frames2 == []


@ffmpeg_only
def test_non_finite_duration_extract_does_not_crash(tmp_path):
    # blocker 2 end-to-end: a real mosaic + Infinity duration must not emit inf ts
    data = _mosaic_bytes(tmp_path)
    info = {"formats": [_fmt(durations=(float("inf"),))]}
    frames, meta = storyboard.extract_storyboard_frames(info, tmp_path / "out", fetch=lambda u: data)
    assert frames == []           # no usable interval -> no tiles, no inf timestamps


def test_no_storyboard_format_fail_open(tmp_path):
    frames, meta = storyboard.extract_storyboard_frames(
        {"formats": [{"format_id": "137"}]}, tmp_path / "out")
    assert frames == [] and meta["note"] == "no-storyboard-format"


def test_rejects_non_ytimg_host():
    # concern 4: only https i.ytimg.com URLs are fetchable
    assert storyboard._allowed_url("https://i.ytimg.com/sb/x/M0.jpg")
    assert not storyboard._allowed_url("http://i.ytimg.com/sb/x/M0.jpg")   # not https
    assert not storyboard._allowed_url("https://evil.example.com/x.jpg")   # wrong host
    assert not storyboard._allowed_url("https://i.ytimg.com.evil.com/x")   # suffix spoof
    assert not storyboard._allowed_url("file:///etc/passwd")
    assert not storyboard._allowed_url(None)


@ffmpeg_only
def test_hostile_url_in_fragment_is_not_fetched(tmp_path):
    data = _mosaic_bytes(tmp_path)
    fetched = []

    def spy(url):
        fetched.append(url)
        return data

    fmt = _fmt(durations=(90.0,))
    fmt["fragments"][0]["url"] = "https://evil.example.com/steal"
    frames, _ = storyboard.extract_storyboard_frames(
        {"formats": [fmt]}, tmp_path / "out", fetch=spy)
    assert fetched == [] and frames == []   # rejected before any fetch


def test_http_fetch_enforces_size_cap(monkeypatch):
    """The default fetcher must refuse a body over the per-mosaic cap."""
    class FakeResp:
        def __init__(self, data): self._d = data
        def read(self, n): return self._d[:n]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    big = b"\x00" * (storyboard.MAX_MOSAIC_BYTES + 10)
    monkeypatch.setattr(storyboard.urllib.request, "urlopen", lambda *a, **k: FakeResp(big))
    with pytest.raises(ValueError):
        storyboard._http_fetch("https://i.ytimg.com/sb/x/M0.jpg")


@ffmpeg_only
def test_total_bytes_cap_stops_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(storyboard, "MAX_TOTAL_BYTES", 10)  # trip after first mosaic
    data = _mosaic_bytes(tmp_path)
    fetched = []

    def spy(url):
        fetched.append(url)
        return data

    info = {"formats": [_fmt(durations=(90.0,) * 5)]}
    storyboard.extract_storyboard_frames(info, tmp_path / "out", max_frames=5, fetch=spy)
    assert len(fetched) == 1  # stopped after the first mosaic blew the total cap
