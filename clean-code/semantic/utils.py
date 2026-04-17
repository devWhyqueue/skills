from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

import yaml


@dataclass(frozen=True)
class Rule:
    """A single semantic rule from the rules file."""

    id: str
    statement: str


def load_rules(path: Path) -> list[Rule]:
    """Load SEMANTIC rules from a YAML file."""
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


def utc_now_iso() -> str:
    """Return current UTC time as ISO string (no microseconds)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def posix(path: Path) -> str:
    """Return path as POSIX-style string."""
    return path.as_posix().replace("\\", "/")


def truncate(text: str, *, max_chars: int) -> str:
    """Truncate text to max_chars, keeping head and tail with an ellipsis in the middle."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head].rstrip()
        + "\n\n... (diff truncated) ...\n\n"
        + text[-keep_tail:].lstrip()
    )


def file_line_count(path: str) -> int:
    """Return number of lines in the file; 1 on read error."""
    try:
        return len(
            Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except OSError:
        return 1


def file_has_non_whitespace(path: str) -> bool:
    """Return True if the file exists and has non-whitespace content."""
    try:
        return bool(Path(path).read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return False


def safe_slug(path: str, *, max_length: int = 120) -> str:
    """Turn a file path into a safe filename slug (alphanumeric, underscore)."""
    cleaned = path.replace("\\", "/").strip("/")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("_")
    if not slug:
        slug = "file"
    if len(slug) > max_length:
        digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
        slug = f"{slug[: max_length - 11]}_{digest}"
    return slug
