from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from semantic.rules import Rule, load_rules
from semantic.utils import file_line_count, posix, safe_slug, utc_now_iso


ALLOWED_STATUSES = {"PASS", "FAIL", "NEEDS_HUMAN", "NA"}


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        width=120,
        allow_unicode=True,
    )


def new_ledger(
    *,
    rules_path: Path,
    base_ref: str,
    head_ref: str,
    files: list[str],
    rules: list[Rule],
) -> dict[str, Any]:
    return {
        "version": 1,
        "meta": {
            "generated_at_utc": utc_now_iso(),
            "rules_path": posix(rules_path),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": [
            {
                "path": path,
                "rules": [
                    {
                        "id": rule.id,
                        "status": "NEEDS_HUMAN",
                        "evidence": [
                            {
                                "symbol": "<module>",
                                "lines": {
                                    "start": 1,
                                    "end": max(1, file_line_count(path)),
                                },
                                "message": f"Pending semantic review for {rule.id}: {rule.statement}",
                            }
                        ],
                    }
                    for rule in rules
                ],
            }
            for path in files
        ],
    }


def _normalize_evidence_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    symbol = str(item.get("symbol", "")).strip()
    message = str(item.get("message", "")).strip()
    lines = item.get("lines", {})
    if not isinstance(lines, dict):
        lines = {}
    try:
        start = int(lines.get("start"))
        end = int(lines.get("end"))
    except Exception:
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


def normalize_ledger(
    *,
    ledger: dict[str, Any],
    files: list[str],
    rules: list[Rule],
    require_pass_evidence: bool = True,
) -> dict[str, Any]:
    rule_ids = [r.id for r in rules]
    rules_by_id = {r.id: r for r in rules}

    existing_files: dict[str, dict[str, Any]] = {}
    raw_files = ledger.get("files", [])
    if isinstance(raw_files, list):
        for raw in raw_files:
            if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                existing_files[raw["path"]] = raw

    normalized_files: list[dict[str, Any]] = []
    fails = 0
    needs_human = 0

    for path in files:
        line_count = file_line_count(path)
        file_entry = existing_files.get(path, {})

        rules_map: dict[str, dict[str, Any]] = {}
        raw_rules = file_entry.get("rules", [])
        if isinstance(raw_rules, list):
            for raw_rule in raw_rules:
                if not isinstance(raw_rule, dict):
                    continue
                rid = str(raw_rule.get("id", "")).strip()
                if rid:
                    rules_map[rid] = raw_rule

        out_rules: list[dict[str, Any]] = []
        for rid in rule_ids:
            raw_rule = rules_map.get(rid, {})
            status = str(raw_rule.get("status", "NEEDS_HUMAN")).strip().upper()
            if status not in ALLOWED_STATUSES:
                status = "NEEDS_HUMAN"

            evidence: list[dict[str, Any]] = []
            raw_evidence = raw_rule.get("evidence", [])
            if isinstance(raw_evidence, list):
                for item in raw_evidence:
                    normalized_item = _normalize_evidence_item(item)
                    if normalized_item is not None:
                        evidence.append(normalized_item)

            if status in {"FAIL", "NEEDS_HUMAN"} and not evidence:
                evidence = [
                    {
                        "symbol": "<module>",
                        "lines": {"start": 1, "end": max(1, int(line_count))},
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
                            "lines": {"start": 1, "end": max(1, int(line_count))},
                            "message": (
                                "PASS requires evidence with a concrete symbol and line range; "
                                f"replace the scaffold placeholder for {rid}."
                            ),
                        }
                    ]

            if status == "FAIL":
                fails += 1
            elif status == "NEEDS_HUMAN":
                needs_human += 1

            out_rules.append(
                {
                    "id": rules_by_id[rid].id,
                    "status": status,
                    "evidence": evidence,
                }
            )

        normalized_files.append({"path": path, "rules": out_rules})

    version = int(ledger.get("version", 1) or 1)
    return {
        "version": version,
        "summary": {"fails": fails, "needs_human": needs_human},
        "files": normalized_files,
    }


def _looks_like_index_ledger(raw: dict[str, Any]) -> bool:
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list) or not raw_files:
        return False
    return any(
        isinstance(entry, dict) and isinstance(entry.get("ledger_path"), str)
        for entry in raw_files
    )


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

    ledger_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
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

    normalized["meta"] = {**meta, **ledger_meta, "phase": phase}
    ledger_path.write_text(dump_yaml(normalized), encoding="utf-8")

    fails = int(normalized.get("summary", {}).get("fails", 0) or 0)
    needs_human = int(normalized.get("summary", {}).get("needs_human", 0) or 0)

    if phase == "scaffold":
        status = "pending"
    elif fails == 0 and needs_human == 0:
        status = "pass"
    elif needs_human:
        status = "requires_reviewer"
    else:
        status = "fail"

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
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    mode = str(meta.get("mode", "")).strip().lower()
    sequential_mode = mode in {"single_file", "sequential"}
    ledger_dir_raw = str(meta.get("ledger_dir", "")).strip()
    ledger_dir = Path(ledger_dir_raw) if ledger_dir_raw else ledger_path.parent / "ledgers"
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list):
        raw_files = []

    if sequential_mode:
        file_entries: list[dict[str, Any]] = []
        fails = 0
        needs_human = 0
        overall_status = "pass"
        missing_count = 0

        for path in files:
            file_ledger_path = ledger_dir / f"{safe_slug(path)}.yml"
            if not file_ledger_path.exists():
                missing_count += 1
                continue

            file_result = _load_and_validate_file_ledger(
                ledger_path=file_ledger_path, files=[path], rules=rules, meta=meta
            )

            file_status = file_result["status"]
            file_summary = file_result["summary"]
            fails += int(file_summary.get("fails", 0) or 0)
            needs_human += int(file_summary.get("needs_human", 0) or 0)

            if file_status == "pending":
                overall_status = "pending"
            elif file_status == "requires_reviewer" and overall_status == "pass":
                overall_status = "requires_reviewer"
            elif file_status == "fail":
                overall_status = "fail"

            prompt_path = ledger_dir.parent / "prompts" / f"{safe_slug(path)}.md"
            file_entries.append(
                {
                    "path": path,
                    "ledger_path": posix(file_ledger_path),
                    "prompt_path": posix(prompt_path) if prompt_path.exists() else "",
                    "status": file_status,
                    "summary": file_summary,
                }
            )

        if missing_count and overall_status == "pass":
            overall_status = "pending"

        phase = "evaluated" if overall_status != "pending" else "scaffold"
        normalized_index = {
            "version": int(raw.get("version", 1) or 1),
            "meta": {**meta, "phase": phase, "mode": mode or "single_file", "ledger_dir": posix(ledger_dir)},
            "summary": {"fails": fails, "needs_human": needs_human},
            "files": file_entries,
        }
        ledger_path.write_text(dump_yaml(normalized_index), encoding="utf-8")

        return {
            "status": overall_status,
            "ledger_path": posix(ledger_path),
            "summary": normalized_index["summary"],
        }

    file_entries: list[dict[str, Any]] = []
    fails = 0
    needs_human = 0
    overall_status = "pass"

    expected_paths = set(files)
    for entry in raw_files:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path", "")).strip()
        ledger_ref = str(entry.get("ledger_path", "")).strip()
        prompt_ref = str(entry.get("prompt_path", "")).strip()
        if not path or not ledger_ref:
            continue
        expected_paths.discard(path)

        file_ledger_path = Path(ledger_ref)
        if not file_ledger_path.exists():
            file_ledger_path.parent.mkdir(parents=True, exist_ok=True)
            file_ledger = new_ledger(
                rules_path=rules_path,
                base_ref=str(meta.get("base_ref", "")),
                head_ref=str(meta.get("head_ref", "")),
                files=[path],
                rules=rules,
            )
            normalized = normalize_ledger(
                ledger=file_ledger, files=[path], rules=rules
            )
            normalized["meta"] = file_ledger["meta"]
            file_ledger_path.write_text(dump_yaml(normalized), encoding="utf-8")

        file_result = _load_and_validate_file_ledger(
            ledger_path=file_ledger_path, files=[path], rules=rules, meta=meta
        )

        file_status = file_result["status"]
        file_summary = file_result["summary"]
        fails += int(file_summary.get("fails", 0) or 0)
        needs_human += int(file_summary.get("needs_human", 0) or 0)

        if file_status == "pending":
            overall_status = "pending"
        elif file_status == "requires_reviewer" and overall_status == "pass":
            overall_status = "requires_reviewer"
        elif file_status == "fail":
            overall_status = "fail"

        file_entries.append(
            {
                "path": path,
                "ledger_path": ledger_ref,
                "prompt_path": prompt_ref,
                "status": file_status,
                "summary": file_summary,
            }
        )

    for missing_path in sorted(expected_paths):
        file_entries.append(
            {
                "path": missing_path,
                "ledger_path": "",
                "prompt_path": "",
                "status": "pending",
                "summary": {"fails": 0, "needs_human": 0},
            }
        )
        overall_status = "pending"

    phase = "evaluated" if overall_status != "pending" else "scaffold"
    normalized_index = {
        "version": int(raw.get("version", 1) or 1),
        "meta": {**meta, "phase": phase},
        "summary": {"fails": fails, "needs_human": needs_human},
        "files": file_entries,
    }
    ledger_path.write_text(dump_yaml(normalized_index), encoding="utf-8")

    return {
        "status": overall_status,
        "ledger_path": posix(ledger_path),
        "summary": normalized_index["summary"],
    }


def load_and_validate_ledger(
    *,
    ledger_path: Path,
    files: list[str],
    rules_path: Path,
) -> dict[str, Any]:
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

    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    return _load_and_validate_file_ledger(
        ledger_path=ledger_path, files=files, rules=rules, meta=meta
    )
