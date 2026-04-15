from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from semantic.utils import Rule, file_line_count, posix, utc_now_iso


ALLOWED_STATUSES = {"PASS", "FAIL", "NEEDS_HUMAN", "NA"}


def dump_yaml(data: dict[str, Any]) -> str:
    """Serialize a dict to YAML string with consistent formatting."""
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        width=120,
        allow_unicode=True,
    )


def _ledger_file_entry(path: str, rules: list[Rule]) -> dict[str, Any]:
    end_line = max(1, file_line_count(path))
    rules_list = [
        {
            "id": rule.id,
            "status": "NEEDS_HUMAN",
            "evidence": [
                {
                    "symbol": "<module>",
                    "lines": {"start": 1, "end": end_line},
                    "message": f"Pending semantic review for {rule.id}: {rule.statement}",
                }
            ],
        }
        for rule in rules
    ]
    return {"path": path, "rules": rules_list}


def new_ledger(
    *,
    rules_path: Path,
    files: list[str],
    rules: list[Rule],
) -> dict[str, Any]:
    """Build a fresh ledger dict for the given files and rules."""
    return {
        "version": 1,
        "meta": {
            "generated_at_utc": utc_now_iso(),
            "rules_path": posix(rules_path),
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": [_ledger_file_entry(p, rules) for p in files],
    }


def _normalize_evidence_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    symbol = str(item.get("symbol", "")).strip()
    message = str(item.get("message", "")).strip()
    lines = item.get("lines", {})
    if not isinstance(lines, dict):
        lines = {}
    start_raw = lines.get("start")
    end_raw = lines.get("end")
    if start_raw is None or end_raw is None:
        return None
    try:
        start = int(start_raw)
        end = int(end_raw)
    except (TypeError, ValueError):
        return None
    if not symbol or not message or start <= 0 or end <= 0:
        return None
    if end < start:
        start, end = end, start
    return {"symbol": symbol, "lines": {"start": start, "end": end}, "message": message}


def _is_placeholder_message(message: str, *, rule: Rule) -> bool:
    return message.strip() in {
        f"Pending semantic review for {rule.id}: {rule.statement}",
        f"Missing evidence; provide symbol, line range, and message for {rule.id}.",
    }


def _existing_files_map(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build path -> file entry map from ledger['files']."""
    out: dict[str, dict[str, Any]] = {}
    raw_files = ledger.get("files", [])
    if isinstance(raw_files, list):
        for raw in raw_files:
            if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                out[raw["path"]] = raw
    return out


def _rules_map_from_file_entry(file_entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract rule id -> raw rule dict from a file entry."""
    rules_map: dict[str, dict[str, Any]] = {}
    raw_rules = file_entry.get("rules", [])
    if isinstance(raw_rules, list):
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, dict):
                continue
            rid = str(raw_rule.get("id", "")).strip()
            if rid:
                rules_map[rid] = raw_rule
    return rules_map


def _evidence_for_rule(
    raw_rule: dict[str, Any], rid: str, line_count: int
) -> list[dict[str, Any]]:
    """Normalize evidence list for one rule; add placeholder if FAIL/NEEDS_HUMAN and empty."""
    evidence: list[dict[str, Any]] = []
    raw_evidence = raw_rule.get("evidence", [])
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            normalized_item = _normalize_evidence_item(item)
            if normalized_item is not None:
                evidence.append(normalized_item)
    return evidence


def _normalize_one_rule(
    *,
    rid: str,
    raw_rule: dict[str, Any],
    rules_by_id: dict[str, Rule],
    line_count: int,
    require_pass_evidence: bool,
) -> tuple[dict[str, Any], int, int]:
    """Normalize one rule entry; return (out_rule, fails_delta, needs_human_delta)."""
    status = str(raw_rule.get("status", "NEEDS_HUMAN")).strip().upper()
    if status not in ALLOWED_STATUSES:
        status = "NEEDS_HUMAN"
    evidence = _evidence_for_rule(raw_rule, rid, line_count)
    if status in {"FAIL", "NEEDS_HUMAN"} and not evidence:
        evidence = [
            {
                "symbol": "<module>",
                "lines": {"start": 1, "end": max(1, line_count)},
                "message": f"Missing evidence; provide symbol, line range, and message for {rid}.",
            }
        ]
    if status == "PASS" and require_pass_evidence:
        if not evidence or all(
            _is_placeholder_message(item.get("message", ""), rule=rules_by_id[rid])
            for item in evidence
        ):
            status = "NEEDS_HUMAN"
            evidence = [
                {
                    "symbol": "<module>",
                    "lines": {"start": 1, "end": max(1, line_count)},
                    "message": (
                        "PASS requires evidence with a concrete symbol and line range; "
                        f"replace the scaffold placeholder for {rid}."
                    ),
                }
            ]
    fail_inc = 1 if status == "FAIL" else 0
    need_inc = 1 if status == "NEEDS_HUMAN" else 0
    out_rule = {"id": rules_by_id[rid].id, "status": status, "evidence": evidence}
    return out_rule, fail_inc, need_inc


def _normalize_file_rules(
    *,
    path: str,
    file_entry: dict[str, Any],
    rule_ids: list[str],
    rules_by_id: dict[str, Rule],
    require_pass_evidence: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """Normalize all rules for one file; return (out_rules, fails, needs_human)."""
    line_count = file_line_count(path)
    rules_map = _rules_map_from_file_entry(file_entry)
    out_rules: list[dict[str, Any]] = []
    fails = 0
    needs_human = 0
    for rid in rule_ids:
        raw_rule = rules_map.get(rid, {})
        out_rule, f, nh = _normalize_one_rule(
            rid=rid,
            raw_rule=raw_rule,
            rules_by_id=rules_by_id,
            line_count=line_count,
            require_pass_evidence=require_pass_evidence,
        )
        out_rules.append(out_rule)
        fails += f
        needs_human += nh
    return out_rules, fails, needs_human


def normalize_ledger(
    *,
    ledger: dict[str, Any],
    files: list[str],
    rules: list[Rule],
    require_pass_evidence: bool = True,
) -> dict[str, Any]:
    """Normalize ledger structure and evidence for consistent validation."""
    rule_ids = [r.id for r in rules]
    rules_by_id = {r.id: r for r in rules}
    existing_files = _existing_files_map(ledger)
    normalized_files: list[dict[str, Any]] = []
    total_fails = 0
    total_needs_human = 0
    for path in files:
        file_entry = existing_files.get(path, {})
        out_rules, fails, needs_human = _normalize_file_rules(
            path=path,
            file_entry=file_entry,
            rule_ids=rule_ids,
            rules_by_id=rules_by_id,
            require_pass_evidence=require_pass_evidence,
        )
        normalized_files.append({"path": path, "rules": out_rules})
        total_fails += fails
        total_needs_human += needs_human
    version = int(ledger.get("version", 1) or 1)
    return {
        "version": version,
        "summary": {"fails": total_fails, "needs_human": total_needs_human},
        "files": normalized_files,
    }
