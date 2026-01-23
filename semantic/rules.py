from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    id: str
    statement: str


def load_rules(path: Path) -> list[Rule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise RuntimeError(f"Invalid rules file (expected list at rules:): {path}")

    rules: list[Rule] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            continue
        enforcement = str(raw.get("enforcement", "")).strip().upper()
        if enforcement != "SEMANTIC":
            continue
        rule_id = str(raw.get("id", "")).strip()
        statement = str(raw.get("statement", "")).strip()
        if rule_id and statement:
            rules.append(Rule(id=rule_id, statement=statement))

    rules.sort(key=lambda r: r.id)
    if not rules:
        raise RuntimeError(
            f"No SEMANTIC rules found in {path} (enforcement: SEMANTIC)."
        )
    return rules
