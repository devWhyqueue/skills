from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Violation:
    rule_id: str
    file: str
    line: int | None
    message: str
    evidence: str | None = None
