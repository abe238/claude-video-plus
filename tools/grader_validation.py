#!/usr/bin/env python3
"""Validate a blinded grader against dual human judgments before release use."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def agreement(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("judgments required")
    required = {"case_id", "human_a", "human_b", "grader"}
    if any(set(row) != required for row in rows):
        raise ValueError("invalid judgment schema")
    labels = sorted({str(row[key]) for row in rows for key in ("human_a", "human_b", "grader")})
    dual = [row for row in rows if row["human_a"] == row["human_b"]]
    if len(dual) < 20:
        raise ValueError("at least 20 dual-human agreements required")
    accuracy = sum(row["grader"] == row["human_a"] for row in dual) / len(dual)
    observed = sum(row["human_a"] == row["grader"] for row in dual) / len(dual)
    human_counts, grader_counts = Counter(row["human_a"] for row in dual), Counter(row["grader"] for row in dual)
    expected = sum((human_counts[label] / len(dual)) * (grader_counts[label] / len(dual)) for label in labels)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {"schema_version": 1, "dual_agreement_cases": len(dual), "accuracy": accuracy,
            "cohen_kappa": kappa, "validated": accuracy >= 0.80 and kappa >= 0.60}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("judgments", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.judgments.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = agreement(rows)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["validated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
