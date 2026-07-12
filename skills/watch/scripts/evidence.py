#!/usr/bin/env python3
"""Compile question-aware evidence (transcript + frames) from a watched video.

Scout -> Retrieve -> Render: chapters structure the deduped transcript, 30s
spans inside chapters are tf-idf scored against a facet-expanded query, whole
chapters roll up under a text budget, a numeric guard rescues price/speed/
benchmark lines buried in unselected chapters, a sufficiency check backfills
any triggered facet that ended up with no evidence, and a span rescue pulls
the top question-scoring spans that live outside every selected chapter.
Coverage questions keep the full transcript plus chapter-anchored frames.

Fail-open contract: any unhandled error prints to stderr and exits 3 so the
caller can fall back to the uniform control sampler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe import parse_vtt  # noqa: E402
from retrieval import conflicts, lexical_rank, obligations, progressive_expand, scout_identity  # noqa: E402
from semantic import hashed_local_rank, remote_rank, uncertainty  # noqa: E402
from state import CacheKey, EvidenceState  # noqa: E402

SPAN_SECONDS = 30.0
PAUSE_GAP_SECONDS = 2.0
BLOCK_SECONDS = 120
DEFAULT_TEXT_BUDGET = 24000
DEFAULT_TARGETED_FRAMES = 12
DEFAULT_COVERAGE_FRAMES = 32
NUMERIC_GUARD_CAP = 12
FACET_EXPANSION_TOP = 3
SPAN_RESCUE_TOP = 8
SPAN_RESCUE_PER_CHAPTER = 2
MIN_OVERLAP = 8
QUESTION_TERM_WEIGHT = 2
FRAME_DEDUPE_SECONDS = 20.0
CHAPTER_FRAME_OFFSET = 10.0
# Reader evidence-token cap is ~26.5k; stay under it with rough estimates
# (~4 chars/token, ~250 tokens per 512px frame) plus headroom.
EVIDENCE_TOKEN_CAP = 25000
TOKENS_PER_CHAR = 0.25
TOKENS_PER_FRAME = 250
MIN_FRAMES = 4

COVERAGE_RE = re.compile(
    r"summari|overview|main (stories|points|topics)|everything|all the", re.I
)
DEICTIC_RE = re.compile(
    r"as you can see|you can see|look at|on ?(the )?screen|right here|this is what"
    r"|check (this |it )?out|shown here",
    re.I,
)
NUMERIC_RE = re.compile(
    r"[$][0-9]|[0-9]+(\.[0-9]+)?%|per million|[0-9,]+ tokens|[0-9]+ (minutes?|seconds?)"
)

FACETS = {
    "cost": ["price", "pricing", "cost", "costs", "cheap", "cheaper", "dollar",
             "dollars", "million", "token", "tokens"],
    "speed": ["fast", "faster", "speed", "minute", "minutes", "second",
              "seconds", "took", "time"],
    "benchmark": ["benchmark", "benchmarks", "score", "scores", "leaderboard",
                  "rank", "best", "top"],
    "features": ["feature", "features", "mode", "modes", "app", "tool",
                 "tools", "does", "can", "new"],
}
NUMERIC_FACETS = {"cost", "speed", "benchmark"}

STOP = set(
    "the a an and or of to in is it for on with that this you i we they as at be are "
    "was were do does did have has had not so if then than but about into just like "
    "can could would will your my our their its what how why when where which there "
    "here".split()
)


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9.']+", text.lower())
            if w not in STOP and len(w) > 1]


def fmt_ts(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def strip_overlap(prev: str, cur: str) -> str:
    """Drop cur's leading words that repeat prev's tail (rolling captions
    re-emit the previous line as the next cue's first line). ponytail: a
    genuine >=8-char word-aligned self-repeat across a cue boundary would be
    stripped too; rare enough to accept."""
    for k in range(min(len(prev), len(cur)), MIN_OVERLAP - 1, -1):
        if (k == len(cur) or cur[k] == " ") and prev.endswith(cur[:k]):
            return cur[k:].lstrip()
    return cur


def dedupe_rolling(segments: list[dict]) -> list[dict]:
    """Collapse rolling-caption overlap left over after parse_vtt's exact-dup
    pass: drop a cue contained in the previous one or whose first half is the
    previous cue's tail, and strip any shorter repeated prefix. Merges a fully
    dropped cue's time range into the keeper."""
    clean: list[dict] = []
    for seg in segments:
        text = seg["text"]
        if clean:
            prev = clean[-1]["text"]
            half = text[: len(text) // 2]
            if text in prev or (half and prev.endswith(half)):
                clean[-1]["end"] = max(clean[-1]["end"], seg["end"])
                continue
            text = strip_overlap(prev, text)
            if not text:
                clean[-1]["end"] = max(clean[-1]["end"], seg["end"])
                continue
        kept = dict(seg)
        kept["text"] = text
        clean.append(kept)
    return clean


def resolve_policy(question: str, policy: str) -> str:
    if policy != "auto":
        return policy
    return "coverage" if COVERAGE_RE.search(question) else "targeted"


def load_chapters(info: dict, segments: list[dict], duration: float) -> list[dict]:
    """info.json chapters; fallback to pause-gap splits, then fixed blocks."""
    chapters: list[dict] = []
    for ch in info.get("chapters") or []:
        try:
            start, end = float(ch["start_time"]), float(ch["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        chapters.append({
            "id": len(chapters),
            "title": str(ch.get("title") or f"Chapter {len(chapters) + 1}"),
            "start": start,
            "end": end,
        })
    if chapters:
        return chapters

    bounds = [0.0]
    for prev, cur in zip(segments, segments[1:]):
        if cur["start"] - prev["end"] > PAUSE_GAP_SECONDS:
            bounds.append(cur["start"])
    if len(bounds) == 1:  # no pauses -> fixed blocks
        bounds = [float(t) for t in range(0, max(1, int(duration)), BLOCK_SECONDS)]
    edges = bounds + [max(duration, bounds[-1] + 1.0)]
    return [
        {"id": i, "title": f"Segment {i + 1} ({fmt_ts(s)}-{fmt_ts(e)})",
         "start": s, "end": e}
        for i, (s, e) in enumerate(zip(edges, edges[1:]))
    ]


def attach_chapters(segments: list[dict], chapters: list[dict]) -> None:
    """Tag each segment with its global index and enclosing chapter id."""
    for i, seg in enumerate(segments):
        seg["i"] = i
        cid = chapters[0]["id"]
        for ch in chapters:
            if seg["start"] >= ch["start"]:
                cid = ch["id"]
            else:
                break
        seg["chapter"] = cid


def build_spans(segments: list[dict], chapters: list[dict]) -> list[dict]:
    """~30s retrieval spans that never cross a chapter boundary."""
    spans: list[dict] = []

    def flush(segs: list[dict], ch_id: int) -> None:
        spans.append({
            "id": len(spans),
            "chapter": ch_id,
            "start": segs[0]["start"],
            "end": segs[-1]["end"],
            "text": " ".join(s["text"] for s in segs),
            "first": segs[0]["i"],
            "last": segs[-1]["i"],
        })

    for ch in chapters:
        cur: list[dict] = []
        for seg in segments:
            if seg["chapter"] != ch["id"]:
                continue
            if cur and seg["start"] - cur[0]["start"] >= SPAN_SECONDS:
                flush(cur, ch["id"])
                cur = []
            cur.append(seg)
        if cur:
            flush(cur, ch["id"])
    return spans


def score_spans(spans: list[dict], query_terms: list[str]) -> list[float]:
    """idf-weighted term overlap normalized by span length (v1 scorer)."""
    docs = [tokenize(sp["text"]) for sp in spans]
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    out: list[float] = []
    for d in docs:
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = sum(tf.get(t, 0) * math.log(1 + n / (1 + df.get(t, n))) for t in query_terms)
        out.append(s / (1 + math.log(1 + len(d))))
    return out


def fit_frame_budget(transcript_chars: int, max_frames: int) -> int:
    """Trim the frame cap so transcript + frames fits the reader token cap.
    The transcript side is policy-mandated (coverage keeps it all), so frames
    are the elastic part. ponytail: a transcript alone can exceed the cap on
    very long videos; frames floor at MIN_FRAMES and transcript trimming
    becomes the upgrade path if that ever bites."""
    remaining = EVIDENCE_TOKEN_CAP - int(transcript_chars * TOKENS_PER_CHAR)
    return min(max_frames, max(MIN_FRAMES, remaining // TOKENS_PER_FRAME))


def extract_frame(video_path: str, ts: float, path: Path) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{ts:.2f}", "-i", str(video_path),
         "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "4", str(path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and path.exists()


def _seg_lines(segments: list[dict], ch_id: int) -> list[str]:
    return [f"[{fmt_ts(s['start'])}] {s['text']}"
            for s in segments if s["chapter"] == ch_id]


def _chapter_anchor(ch: dict, duration: float) -> float:
    ts = ch["start"] + CHAPTER_FRAME_OFFSET
    if ts >= ch["end"]:
        ts = (ch["start"] + ch["end"]) / 2
    return min(ts, max(0.0, duration - 0.5))


def _add_span(sp: dict, reason: str, score: float | None, segments: list[dict],
              chapters: list[dict], evidence: list[dict], blocks: list[tuple],
              pad: int = 0) -> None:
    lo = max(0, sp["first"] - pad)
    hi = min(len(segments) - 1, sp["last"] + pad)
    text = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments[lo:hi + 1])
    title = chapters[sp["chapter"]]["title"]
    t0, t1 = segments[lo]["start"], segments[hi]["end"]
    blocks.append((t0, f"{reason} [{fmt_ts(t0)}-{fmt_ts(t1)}] ({title})", text))
    evidence.append({
        "t_start": fmt_ts(t0), "t_end": fmt_ts(t1), "chapter": title,
        "modalities": ["transcript"], "reason": reason,
        "score": None if score is None else round(score, 3), "frame": None,
    })


def rollup_chapters(ranked: list[int], ch_scores: dict[int, list[float]],
                    segments: list[dict], text_budget: int) -> list[int]:
    """Greedy whole-chapter knapsack: walk the relevance ranking and keep any
    chapter that still fits the budget (top-1 always kept), so one oversized
    chapter does not lock out smaller relevant ones further down."""
    selected: list[int] = []
    chars = 0
    for cid in ranked:
        if selected and max(ch_scores[cid]) <= 0:
            break  # ranking is score-sorted: everything after is zero too
        block = len("\n".join(_seg_lines(segments, cid)))
        if selected and chars + block > text_budget:
            continue
        selected.append(cid)
        chars += block
    return selected


def _targeted(question: str, segments: list[dict], chapters: list[dict],
              spans: list[dict], text_budget: int, duration: float):
    q_tokens = tokenize(question)
    facets = [f for f, lex in FACETS.items() if any(t in lex for t in q_tokens)]
    # Question terms outweigh facet-lexicon terms so lexicon-dense but
    # off-topic chapters cannot outrank chapters that answer the question.
    query_terms = q_tokens * QUESTION_TERM_WEIGHT + [t for f in facets
                                                     for t in FACETS[f]]
    scores = score_spans(spans, query_terms)

    ch_scores: dict[int, list[float]] = {}
    for sp, sc in zip(spans, scores):
        ch_scores.setdefault(sp["chapter"], []).append(sc)
    ranked = sorted(
        ch_scores,
        key=lambda cid: (max(ch_scores[cid]),
                         sum(sorted(ch_scores[cid], reverse=True)[:2])),
        reverse=True,
    )

    selected = rollup_chapters(ranked, ch_scores, segments, text_budget)
    selected_set = set(selected)

    evidence: list[dict] = []
    blocks: list[tuple] = []
    for cid in selected:
        ch = chapters[cid]
        blocks.append((
            ch["start"],
            f"{ch['title']} [{fmt_ts(ch['start'])}-{fmt_ts(ch['end'])}]",
            "\n".join(_seg_lines(segments, cid)),
        ))
        evidence.append({
            "t_start": fmt_ts(ch["start"]), "t_end": fmt_ts(ch["end"]),
            "chapter": ch["title"], "modalities": ["transcript"],
            "reason": "chapter-rollup", "score": round(max(ch_scores[cid]), 3),
            "frame": None,
        })

    span_tokens = [set(tokenize(sp["text"])) for sp in spans]
    chosen = {sp["id"] for sp in spans if sp["chapter"] in selected_set}

    # Numeric guard: whole-chapter roll-up misses number-dense lines (pricing
    # tables etc.) living inside unselected chapters; rescue them directly.
    guard_frames: list[tuple] = []
    if NUMERIC_FACETS & set(facets):
        span_by_seg = {i: sp for sp in spans
                       for i in range(sp["first"], sp["last"] + 1)}
        guard_count = 0
        for seg in segments:
            if guard_count >= NUMERIC_GUARD_CAP:
                break
            if seg["chapter"] in selected_set or not NUMERIC_RE.search(seg["text"]):
                continue
            sp = span_by_seg.get(seg["i"])
            if sp is None or sp["id"] in chosen:
                continue
            chosen.add(sp["id"])
            guard_count += 1
            _add_span(sp, "numeric-guard", None, segments, chapters,
                      evidence, blocks, pad=1)
            # Numbers are usually on screen (pricing tables, benchmark charts):
            # grab the guarded span's midpoint frame too.
            guard_frames.append(((sp["start"] + sp["end"]) / 2, "numeric-guard",
                                 chapters[sp["chapter"]]["title"]))

    # Sufficiency: every triggered facet needs >=1 selected span mentioning it.
    covered: set[str] = set()
    for sp in spans:
        if sp["id"] in chosen:
            covered |= span_tokens[sp["id"]]
    for facet in facets:
        if set(FACETS[facet]) & covered:
            continue
        fscores = score_spans(spans, FACETS[facet])
        order = sorted(range(len(spans)), key=lambda i: -fscores[i])
        added = 0
        for i in order:
            if added >= FACET_EXPANSION_TOP or fscores[i] <= 0:
                break
            if spans[i]["id"] in chosen:
                continue
            chosen.add(spans[i]["id"])
            covered |= span_tokens[i]
            _add_span(spans[i], "facet-expansion", fscores[i], segments,
                      chapters, evidence, blocks)
            added += 1

    # Span rescue: top question-scoring spans outside every selected chapter.
    # Catches question-relevant facts (release dates, cross-references) that
    # carry no numbers and whose home chapter did not make the roll-up.
    # Per-chapter cap keeps one dense unselected chapter from eating the cap.
    rescued = 0
    rescued_per_ch: dict[int, int] = {}
    for i in sorted(range(len(spans)), key=lambda i: -scores[i]):
        if rescued >= SPAN_RESCUE_TOP or scores[i] <= 0:
            break
        sp = spans[i]
        if (sp["id"] in chosen or sp["chapter"] in selected_set
                or rescued_per_ch.get(sp["chapter"], 0) >= SPAN_RESCUE_PER_CHAPTER):
            continue
        chosen.add(sp["id"])
        rescued += 1
        rescued_per_ch[sp["chapter"]] = rescued_per_ch.get(sp["chapter"], 0) + 1
        _add_span(sp, "span-rescue", scores[i], segments, chapters,
                  evidence, blocks, pad=1)

    frame_specs: list[tuple] = []
    for cid in sorted(selected, key=lambda c: chapters[c]["start"]):
        ch = chapters[cid]
        frame_specs.append((_chapter_anchor(ch, duration), "chapter-start", ch["title"]))
    frame_specs.extend(guard_frames)
    for seg in segments:
        if seg["chapter"] in selected_set and DEICTIC_RE.search(seg["text"]):
            frame_specs.append(
                (seg["start"], "deictic-cue", chapters[seg["chapter"]]["title"]))
    return evidence, blocks, selected_set, frame_specs


def _coverage(segments: list[dict], chapters: list[dict], duration: float,
              max_frames: int):
    text = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments)
    blocks = [(0.0, "Full transcript", text)]
    evidence = [{
        "t_start": fmt_ts(0), "t_end": fmt_ts(duration), "chapter": None,
        "modalities": ["transcript"], "reason": "coverage-full-transcript",
        "score": None, "frame": None,
    }]
    frame_specs: list[tuple] = []
    for ch in chapters:
        frame_specs.append((_chapter_anchor(ch, duration), "chapter-start", ch["title"]))
    for seg in segments:
        if DEICTIC_RE.search(seg["text"]):
            frame_specs.append(
                (seg["start"], "deictic-cue", chapters[seg["chapter"]]["title"]))
    for i in range(max_frames):
        frame_specs.append((duration * (i + 0.5) / max_frames, "uniform-fill", None))
    return evidence, blocks, {ch["id"] for ch in chapters}, frame_specs


def compile_evidence(vtt_path: str, video_path: str, info_path: str,
                     question: str, out_dir: Path, policy: str = "auto",
                     max_frames: int | None = None,
                     text_budget: int = DEFAULT_TEXT_BUDGET,
                     semantic_backend: str = "off",
                     semantic_endpoint: str | None = None,
                     semantic_model: str = "default",
                     allow_remote_semantic: bool = False,
                     acquisition: dict | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = json.loads(Path(info_path).read_text(encoding="utf-8"))
    source_identity = hashlib.sha256(
        str(info.get("id") or info.get("webpage_url") or video_path).encode()
    ).hexdigest()
    state = EvidenceState()
    cache_key = CacheKey(source_identity=source_identity, adapter="captions", model="vtt",
                         policy="scout-v1")
    state_enabled = os.environ.get("WATCH_STATE", "0") == "1"
    cached = state.get(cache_key) if state_enabled else None
    if cached and cached.status == "hit" and isinstance(cached.payload, dict):
        segments = cached.payload.get("segments", [])
        scout_reuse = "verified-hit"
    else:
        segments = dedupe_rolling(parse_vtt(str(vtt_path)))
        scout_reuse = "miss"
        if segments and state_enabled:
            state = EvidenceState(allow_sensitive=True)
            state.put(cache_key, {"segments": segments}, payload_kind="scout")
    if not segments:
        raise ValueError(f"no transcript segments parsed from {vtt_path}")
    duration = float(info.get("duration") or segments[-1]["end"])
    chapters = load_chapters(info, segments, duration)
    attach_chapters(segments, chapters)
    spans = build_spans(segments, chapters)
    lexical = lexical_rank(question, segments, limit=16)
    required_obligations = obligations(question)
    expanded = progressive_expand(question, lexical, segments,
                                  {row["index"] for row in lexical[:8]})
    semantic_receipt = None
    semantic_scores: list[float] = []
    if semantic_backend != "off" and uncertainty(lexical, required_obligations):
        texts = [str(row["segment"].get("text", "")) for row in lexical]
        if semantic_backend == "local":
            semantic_scores, semantic_receipt = hashed_local_rank(question, texts)
        elif semantic_backend == "remote" and semantic_endpoint:
            semantic_scores, semantic_receipt = remote_rank(
                semantic_endpoint, semantic_model, question, texts,
                authorized=allow_remote_semantic,
            )

    policy = resolve_policy(question, policy)
    if max_frames is None:
        max_frames = DEFAULT_TARGETED_FRAMES if policy == "targeted" else DEFAULT_COVERAGE_FRAMES

    if policy == "targeted":
        evidence, blocks, selected_set, frame_specs = _targeted(
            question, segments, chapters, spans, text_budget, duration)
    else:
        evidence, blocks, selected_set, frame_specs = _coverage(
            segments, chapters, duration, max_frames)

    # Frames: dedupe within FRAME_DEDUPE_SECONDS in priority order, then cap.
    # The cap shrinks when the transcript already eats most of the token budget.
    transcript_chars = sum(len(text) for _, _, text in blocks)
    max_frames = fit_frame_budget(transcript_chars, max_frames)
    kept: list[tuple] = []
    for ts, reason, cht in frame_specs:
        if any(abs(ts - k[0]) < FRAME_DEDUPE_SECONDS for k in kept):
            continue
        kept.append((ts, reason, cht))
        if len(kept) >= max_frames:
            break
    kept.sort(key=lambda k: k[0])

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame_entries: list[dict] = []
    for ts, reason, cht in kept:
        path = frames_dir / f"t{int(ts) // 60:02d}m{int(ts) % 60:02d}s.jpg"
        if extract_frame(video_path, ts, path):
            frame_entries.append({
                "t_start": fmt_ts(ts), "t_end": fmt_ts(ts), "chapter": cht,
                "modalities": ["frame"], "reason": reason, "score": None,
                "frame": str(path),
            })
    evidence.extend(frame_entries)

    manifest = {
        "schema_version": 1,
        "policy": policy,
        "question": question,
        "chapters": [
            {"title": ch["title"], "start": ch["start"], "end": ch["end"],
             "selected": ch["id"] in selected_set}
            for ch in chapters
        ],
        "evidence": evidence,
        "reader_cost": {"transcript_chars": transcript_chars,
                        "frames": len(frame_entries)},
        "retrieval": {
            "engine": "lexical-v1",
            "obligations": required_obligations,
            "ranked_segments": [
                {"index": row["index"], "score": row["score"],
                 "start": row["segment"].get("start"), "end": row["segment"].get("end")}
                for row in lexical
            ],
            "conflicts": conflicts([row["segment"] for row in lexical]),
            "scout_identity": scout_identity(source_identity, segments),
            "scout_reuse": scout_reuse,
            "progressive_verification": expanded,
        },
        "semantic": {
            "requested": semantic_backend,
            "triggered": semantic_receipt is not None,
            "scores": semantic_scores,
            "receipt": semantic_receipt.__dict__ if semantic_receipt else None,
        },
        "vision": {"backend": "ffmpeg-stdlib-v1", "opencv_included": False},
        "acquisition": acquisition or {},
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Evidence report",
        f"Question: {question}",
        f"Policy: {policy}",
        "",
        "## Selected chapters",
    ]
    for ch in chapters:
        if ch["id"] in selected_set:
            lines.append(f"- {ch['title']} [{fmt_ts(ch['start'])}-{fmt_ts(ch['end'])}]")
    lines += ["", "## Frames"]
    for e in frame_entries:
        lines.append(f"- t={e['t_start']} {e['frame']} ({e['reason']})")
    lines += ["", "## Transcript evidence"]
    for _, header, text in sorted(blocks, key=lambda b: b[0]):
        lines += ["", f"### {header}", text]
    (out_dir / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "policy": policy,
        "selected_chapters": [ch["title"] for ch in chapters
                              if ch["id"] in selected_set],
        "reader_cost": manifest["reader_cost"],
        "manifest": str(out_dir / "manifest.json"),
        "report": str(out_dir / "report.txt"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile question-aware evidence (manifest + report) from a video.")
    parser.add_argument("--vtt", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--info", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--policy", choices=["auto", "targeted", "coverage"],
                        default="auto")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--text-budget", type=int, default=DEFAULT_TEXT_BUDGET)
    parser.add_argument("--semantic", choices=["off", "local", "remote"], default="off")
    parser.add_argument("--semantic-endpoint")
    parser.add_argument("--semantic-model", default="default")
    parser.add_argument("--allow-remote-semantic", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = compile_evidence(
            args.vtt, args.video, args.info, args.question, Path(args.out_dir),
            policy=args.policy, max_frames=args.max_frames,
            text_budget=args.text_budget,
            semantic_backend=args.semantic,
            semantic_endpoint=args.semantic_endpoint,
            semantic_model=args.semantic_model,
            allow_remote_semantic=args.allow_remote_semantic,
        )
    except Exception as exc:  # fail-open: caller falls back to control sampler
        print(f"evidence: fail-open ({exc})", file=sys.stderr)
        return 3

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
