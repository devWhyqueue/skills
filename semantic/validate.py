from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from semantic.ledger import dump_yaml, normalize_ledger
from semantic.utils import Rule, load_rules, posix
from semantic.validate_index import (
    validate_index_from_entries,
    validate_index_sequential,
)


def _looks_like_index_ledger(raw: dict[str, Any]) -> bool:
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list) or not raw_files:
        return False
    return any(
        isinstance(entry, dict) and isinstance(entry.get("ledger_path"), str)
        for entry in raw_files
    )


def _file_ledger_phase(normalized: dict[str, Any], ledger_meta: dict[str, Any]) -> str:
    """Compute phase (scaffold vs evaluated) for a file ledger."""
    phase = str(ledger_meta.get("phase", "")).strip().lower()
    any_reviewed = any(
        str(rule.get("status", "")).strip().upper() in {"PASS", "FAIL", "NA"}
        for file_entry in normalized.get("files", [])
        for rule in (
            file_entry.get("rules", []) if isinstance(file_entry, dict) else []
        )
        if isinstance(rule, dict)
    )
    if phase != "evaluated" and any_reviewed:
        phase = "evaluated"
    if phase not in {"scaffold", "evaluated"}:
        phase = "evaluated" if any_reviewed else "scaffold"
    return phase


def _file_ledger_status(phase: str, fails: int, needs_human: int) -> str:
    """Compute validation status from phase and summary counts."""
    if phase == "scaffold":
        return "pending"
    if fails == 0 and needs_human == 0:
        return "pass"
    if needs_human:
        return "requires_reviewer"
    return "fail"


def _load_and_validate_file_ledger(
    *,
    ledger_path: Path,
    files: list[str],
    rules: list[Rule],
    meta: dict[str, Any],
) -> dict[str, Any]:
    raw_any = (
        yaml.safe_load(ledger_path.read_text(encoding="utf-8", errors="replace")) or {}
    )
    raw = raw_any if isinstance(raw_any, dict) else {}
    normalized = normalize_ledger(ledger=raw, files=files, rules=rules)
    meta_raw = raw.get("meta")
    ledger_meta: dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
    phase = _file_ledger_phase(normalized, ledger_meta)
    normalized["meta"] = {**meta, **ledger_meta, "phase": phase}
    ledger_path.write_text(dump_yaml(normalized), encoding="utf-8")
    summary_raw = normalized.get("summary", {})
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    fails = int(summary.get("fails", 0) or 0)
    needs_human = int(summary.get("needs_human", 0) or 0)
    status = _file_ledger_status(phase, fails, needs_human)
    return {
        "status": status,
        "ledger_path": posix(ledger_path),
        "summary": normalized["summary"],
        "files": normalized.get("files", []),
    }


def _load_and_validate_index_ledger(
    *,
    ledger_path: Path,
    files: list[str],
    rules: list[Rule],
    rules_path: Path,
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Load and validate an index ledger; dispatch to sequential or entries mode."""
    meta_raw = raw.get("meta")
    meta: dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
    mode = str(meta.get("mode", "")).strip().lower()
    sequential_mode = mode in {"single_file", "sequential", "batched_sequential"}
    ledger_dir_raw = str(meta.get("ledger_dir", "")).strip()
    ledger_dir = (
        Path(ledger_dir_raw) if ledger_dir_raw else ledger_path.parent / "ledgers"
    )
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list):
        raw_files = []
    if sequential_mode:
        return validate_index_sequential(
            ledger_path=ledger_path,
            files=files,
            rules=rules,
            raw=raw,
            meta=meta,
            ledger_dir=ledger_dir,
            mode=mode,
            validate_file_ledger=_load_and_validate_file_ledger,
        )
    return validate_index_from_entries(
        ledger_path=ledger_path,
        files=files,
        rules=rules,
        rules_path=rules_path,
        raw=raw,
        meta=meta,
        raw_files=raw_files,
        validate_file_ledger=_load_and_validate_file_ledger,
    )


def load_and_validate_ledger(
    *,
    ledger_path: Path,
    files: list[str],
    rules_path: Path,
) -> dict[str, Any]:
    """Load a ledger from path and validate; return status and summary."""
    rules = load_rules(rules_path)
    raw_any = (
        yaml.safe_load(ledger_path.read_text(encoding="utf-8", errors="replace")) or {}
    )
    raw = raw_any if isinstance(raw_any, dict) else {}
    if _looks_like_index_ledger(raw):
        return _load_and_validate_index_ledger(
            ledger_path=ledger_path,
            files=files,
            rules=rules,
            rules_path=rules_path,
            raw=raw,
        )
    file_meta_raw = raw.get("meta")
    file_meta: dict[str, Any] = file_meta_raw if isinstance(file_meta_raw, dict) else {}
    return _load_and_validate_file_ledger(
        ledger_path=ledger_path, files=files, rules=rules, meta=file_meta
    )
