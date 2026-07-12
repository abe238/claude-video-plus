"""Versioned, bounded transport for a /watch question and evidence budget."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


MAX_QUESTION_BYTES = 16_384
MAX_BUDGET = 200_000


@dataclass(frozen=True)
class WatchRequest:
    source: str
    question: str = ""
    detail: str = "balanced"
    text_budget: int = 24_000
    max_frames: int | None = None
    schema_version: int = 1

    def validate(self) -> "WatchRequest":
        if self.schema_version != 1:
            raise ValueError("unsupported request schema")
        if not self.source or "\x00" in self.source:
            raise ValueError("source is required and cannot contain NUL")
        if len(self.question.encode("utf-8")) > MAX_QUESTION_BYTES:
            raise ValueError("question exceeds 16 KiB")
        if self.detail not in {"transcript", "efficient", "balanced", "token-burner", "evidence"}:
            raise ValueError("invalid detail")
        if not 1 <= self.text_budget <= MAX_BUDGET:
            raise ValueError("invalid text budget")
        if self.max_frames is not None and not 1 <= self.max_frames <= 10_000:
            raise ValueError("invalid frame budget")
        return self

    def to_json(self) -> str:
        self.validate()
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_file(cls, path: str | Path) -> "WatchRequest":
        raw = Path(path).read_bytes()
        if len(raw) > MAX_QUESTION_BYTES + 4096:
            raise ValueError("request file too large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("unknown request field")
        return cls(**data).validate()
