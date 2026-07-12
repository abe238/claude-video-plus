"""Dependency-free lexical retrieval, obligations, conflicts, and Scout reuse."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._:/-][A-Za-z0-9]+)*")
NUMBER_RE = re.compile(r"(?<!\w)(?:[$€£])?\d[\d,.]*(?:%|x|ms|s|gb|mb|kb)?", re.I)
NEGATION = {"no", "not", "never", "without", "cannot", "can't", "won't", "isn't", "doesn't"}
TEMPORAL = {"before", "after", "then", "next", "previous", "change", "become", "start", "end"}


def tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def lexical_rank(question: str, segments: list[dict], limit: int = 12) -> list[dict]:
    query = tokens(question)
    if not query:
        return []
    documents = [tokens(str(segment.get("text", ""))) for segment in segments]
    df = {term: sum(term in document for document in documents) for term in set(query)}
    ranked = []
    for index, (segment, document) in enumerate(zip(segments, documents)):
        counts = {term: document.count(term) for term in set(query)}
        score = sum((1 + math.log(count)) * math.log((len(documents) + 1) / (df[term] + 0.5))
                    for term, count in counts.items() if count)
        exact = sum(2.0 for value in NUMBER_RE.findall(question) if value.lower() in str(segment.get("text", "")).lower())
        negation = 1.0 if set(query) & NEGATION and set(document) & NEGATION else 0.0
        if score + exact + negation > 0:
            ranked.append({"index": index, "score": round(score + exact + negation, 6), "segment": segment})
    return sorted(ranked, key=lambda row: (-row["score"], float(row["segment"].get("start", 0)), row["index"]))[:limit]


def obligations(question: str) -> list[str]:
    terms = set(tokens(question))
    result = ["answer"]
    if NUMBER_RE.search(question):
        result.append("exact-number")
    if terms & NEGATION:
        result.append("negation")
    if terms & TEMPORAL:
        result.extend(["before-state", "after-state"])
    return result


def progressive_expand(question: str, ranked: list[dict], all_segments: list[dict],
                       selected_indices: set[int], max_expansions: int = 4) -> dict:
    """Expand only around unmet obligations; never reopen the full timeline."""
    required = obligations(question)
    chosen = set(selected_indices)
    expansions = []
    def combined() -> str:
        return " ".join(str(all_segments[index].get("text", "")) for index in sorted(chosen))
    for obligation in required:
        text = combined().lower()
        satisfied = obligation == "answer" and bool(chosen)
        satisfied |= obligation == "exact-number" and bool(NUMBER_RE.search(text))
        satisfied |= obligation == "negation" and bool(set(tokens(text)) & NEGATION)
        satisfied |= obligation == "before-state" and any(term in text for term in ("before", "initial", "first"))
        satisfied |= obligation == "after-state" and any(term in text for term in ("after", "then", "finally", "next"))
        if satisfied:
            continue
        candidates = [row for row in ranked if row["index"] not in chosen]
        if not candidates or len(expansions) >= max_expansions:
            break
        index = candidates[0]["index"]
        neighborhood = [value for value in (index - 1, index, index + 1) if 0 <= value < len(all_segments)]
        chosen.update(neighborhood)
        expansions.append({"obligation": obligation, "indices": neighborhood})
    return {"selected_indices": sorted(chosen), "expansions": expansions,
            "bounded": len(expansions) <= max_expansions}


def conflicts(segments: list[dict]) -> list[dict]:
    claims: dict[tuple[str, str], list[dict]] = {}
    for segment in segments:
        text = str(segment.get("text", ""))
        subject = " ".join(token for token in tokens(text) if token not in NEGATION)[:80]
        for number in NUMBER_RE.findall(text):
            claims.setdefault((subject, number.lower()), []).append(segment)
    grouped: dict[str, list[tuple[str, list[dict]]]] = {}
    for (subject, value), rows in claims.items():
        grouped.setdefault(subject, []).append((value, rows))
    return [{"subject": subject, "values": [{"value": value, "segments": rows} for value, rows in values]}
            for subject, values in grouped.items() if len(values) > 1]


def scout_identity(source_identity: str, segments: list[dict], version: str = "scout-v1") -> str:
    canonical = json.dumps({"source": source_identity, "segments": segments, "version": version},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_scout(path: Path, source_identity: str, segments: list[dict]) -> dict:
    payload = {"schema_version": 1, "source_identity": source_identity,
               "scout_identity": scout_identity(source_identity, segments), "segments": segments}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return payload


def read_scout(path: Path, source_identity: str) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source_identity") != source_identity:
            return None
        if payload.get("scout_identity") != scout_identity(source_identity, payload.get("segments", [])):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
