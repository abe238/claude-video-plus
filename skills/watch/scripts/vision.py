"""Dependency-free visual event selection policies; OpenCV intentionally excluded."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualCandidate:
    timestamp: float
    scene_delta: float = 0.0
    luminance_delta: float = 0.0
    edge_delta: float = 0.0
    transcript_cue: bool = False


def score(candidate: VisualCandidate) -> float:
    return (0.55 * max(0.0, candidate.scene_delta) +
            0.25 * max(0.0, candidate.edge_delta) +
            0.20 * max(0.0, candidate.luminance_delta) +
            (1.0 if candidate.transcript_cue else 0.0))


def select(candidates: list[VisualCandidate], budget: int, min_spacing: float = 1.0) -> list[VisualCandidate]:
    if budget < 1:
        return []
    ranked = sorted(candidates, key=lambda item: (-score(item), item.timestamp))
    kept: list[VisualCandidate] = []
    for candidate in ranked:
        if all(abs(candidate.timestamp - other.timestamp) >= min_spacing for other in kept):
            kept.append(candidate)
        if len(kept) == budget:
            break
    return sorted(kept, key=lambda item: item.timestamp)


def ablation_receipt(control: dict, candidate: dict) -> dict:
    metrics = ("event_recall", "duplicate_rate", "reader_tokens", "answer_quality", "wall_ms", "install_bytes")
    complete = all(metric in control and metric in candidate for metric in metrics)
    wins = complete and candidate["event_recall"] >= control["event_recall"] and candidate["answer_quality"] >= control["answer_quality"] and candidate["duplicate_rate"] <= control["duplicate_rate"] and candidate["reader_tokens"] <= control["reader_tokens"] and candidate["wall_ms"] <= control["wall_ms"] and candidate["install_bytes"] <= control["install_bytes"]
    return {"schema_version": 1, "backend": "ffmpeg-stdlib-v1", "opencv_included": False,
            "complete": complete, "pareto_promote": bool(wins), "control": control, "candidate": candidate}
