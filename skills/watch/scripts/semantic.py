"""Optional fail-open semantic adapters with explicit privacy boundaries."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticReceipt:
    backend: str
    model: str
    transmitted_bytes: int
    calls: int
    status: str
    error: str | None = None


def uncertainty(lexical_rows: list[dict], obligations: list[str]) -> bool:
    if not lexical_rows:
        return True
    scores = [float(row.get("score", 0)) for row in lexical_rows]
    close = len(scores) > 1 and scores[0] > 0 and scores[1] / scores[0] >= 0.92
    return close or len(obligations) > 2


def hashed_local_rank(question: str, texts: list[str]) -> tuple[list[float], SemanticReceipt]:
    """Cheap deterministic local semantic proxy; no model/download and no transmission."""
    q = hashlib.sha256(question.casefold().encode()).digest()
    scores = []
    for text in texts:
        digest = hashlib.sha256(text.casefold().encode()).digest()
        scores.append(sum(a == b for a, b in zip(q, digest)) / len(q))
    return scores, SemanticReceipt("local-hash", "sha256-v1", 0, 0, "ok")


def remote_rank(endpoint: str, model: str, question: str, texts: list[str], *, authorized: bool) -> tuple[list[float], SemanticReceipt]:
    if not authorized:
        raise PermissionError("remote semantic transmission requires explicit authorization")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("remote semantic endpoint must be explicit HTTPS")
    body = json.dumps({"model": model, "question": question, "texts": texts}, ensure_ascii=False).encode()
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        scores = [float(value) for value in payload["scores"]]
        if len(scores) != len(texts):
            raise ValueError("semantic score count mismatch")
        return scores, SemanticReceipt("remote", model, len(body), 1, "ok")
    except Exception as exc:
        return [], SemanticReceipt("remote", model, len(body), 1, "fail-open", type(exc).__name__)


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
