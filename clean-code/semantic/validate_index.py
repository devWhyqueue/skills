"""Index-ledger validation (sequential and from-entries modes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from semantic.ledger import dump_yaml, new_ledger, normalize_ledger
from semantic.utils import Rule, posix, safe_slug


def _write_index_and_return(
    *,
    ledger_path: Path,
    raw: dict[str, Any],
    meta: dict[str, Any],
    file_entries: list[dict[str, Any]],
    fails: int,
    needs_human: int,
    overall_status: str,
    ledger_dir: Path | None = None,
    mode: str = "",
) -> dict[str, Any]:
    """Build normalized index, write it, return status dict."""
    phase = "evaluated" if overall_status != "pending" else "scaffold"
    meta_part: dict[str, Any] = {**meta, "phase": phase}
    if ledger_dir is not None:
        meta_part["mode"] = mode or "single_file"
        meta_part["ledger_dir"] = posix(ledger_dir)
    normalized_index = {
        "version": int(raw.get("version", 1) or 1),
        "meta": meta_part,
        "summary": {"fails": fails, "needs_human": needs_human},
        "files": file_entries,
    }
    ledger_path.write_text(dump_yaml(normalized_index), encoding="utf-8")
    return {
        "status": overall_status,
        "ledger_path": posix(ledger_path),
        "summary": normalized_index["summary"],
    }


def _merge_status(current: str, file_status: str) -> str:
    """Merge file_status into current overall status."""
    if file_status == "pending":
        return "pending"
    if file_status == "requires_reviewer" and current == "pass":
        return "requires_reviewer"
    if file_status == "fail":
        return "fail"
    return current


def _sequential_one(
    path: str,
    ledger_dir: Path,
    rules: list[Rule],
    meta: dict[str, Any],
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], int, int]:
    """Validate one file in sequential mode; return (entry, fails_delta, needs_human_delta)."""
    file_ledger_path = ledger_dir / f"{safe_slug(path)}.yml"
    file_result = validate_file_ledger(
        ledger_path=file_ledger_path, files=[path], rules=rules, meta=meta
    )
    prompt_path = ledger_dir.parent / "prompts" / f"{safe_slug(path)}.md"
    entry = {
        "path": path,
        "ledger_path": posix(file_ledger_path),
        "prompt_path": posix(prompt_path) if prompt_path.exists() else "",
        "status": file_result["status"],
        "summary": file_result["summary"],
    }
    s = file_result["summary"]
    return entry, int(s.get("fails", 0) or 0), int(s.get("needs_human", 0) or 0)


def _collect_sequential_entries(
    files: list[str],
    ledger_dir: Path,
    rules: list[Rule],
    meta: dict[str, Any],
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, int, str]:
    """Run sequential validation; return (file_entries, fails, needs_human, missing_count, overall_status)."""
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
        entry, f, nh = _sequential_one(
            path, ledger_dir, rules, meta, validate_file_ledger
        )
        file_entries.append(entry)
        fails += f
        needs_human += nh
        overall_status = _merge_status(overall_status, entry["status"])
    if missing_count and overall_status == "pass":
        overall_status = "pending"
    return file_entries, fails, needs_human, missing_count, overall_status


def validate_index_sequential(
    *,
    ledger_path: Path,
    files: list[str],
    rules: list[Rule],
    raw: dict[str, Any],
    meta: dict[str, Any],
    ledger_dir: Path,
    mode: str,
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Validate index ledger in sequential mode; return status dict."""
    file_entries, fails, needs_human, _, overall_status = _collect_sequential_entries(
        files, ledger_dir, rules, meta, validate_file_ledger
    )
    return _write_index_and_return(
        ledger_path=ledger_path,
        raw=raw,
        meta=meta,
        file_entries=file_entries,
        fails=fails,
        needs_human=needs_human,
        overall_status=overall_status,
        ledger_dir=ledger_dir,
        mode=mode,
    )


def _entries_process_one(
    entry: dict[str, Any],
    rules: list[Rule],
    rules_path: Path,
    meta: dict[str, Any],
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], int, int] | None:
    """Process one raw file entry; return (file_entry, fails_delta, needs_human_delta) or None."""
    path = str(entry.get("path", "")).strip()
    ledger_ref = str(entry.get("ledger_path", "")).strip()
    prompt_ref = str(entry.get("prompt_path", "")).strip()
    if not path or not ledger_ref:
        return None
    file_ledger_path = Path(ledger_ref)
    if not file_ledger_path.exists():
        file_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        file_ledger = new_ledger(rules_path=rules_path, files=[path], rules=rules)
        normalized = normalize_ledger(ledger=file_ledger, files=[path], rules=rules)
        normalized["meta"] = file_ledger["meta"]
        file_ledger_path.write_text(dump_yaml(normalized), encoding="utf-8")
    file_result = validate_file_ledger(
        ledger_path=file_ledger_path, files=[path], rules=rules, meta=meta
    )
    out_entry = {
        "path": path,
        "ledger_path": ledger_ref,
        "prompt_path": prompt_ref,
        "status": file_result["status"],
        "summary": file_result["summary"],
    }
    s = file_result["summary"]
    return out_entry, int(s.get("fails", 0) or 0), int(s.get("needs_human", 0) or 0)


def _pending_entry(path: str) -> dict[str, Any]:
    """Build a file entry for a missing/pending path."""
    return {
        "path": path,
        "ledger_path": "",
        "prompt_path": "",
        "status": "pending",
        "summary": {"fails": 0, "needs_human": 0},
    }


def _process_raw_entries(
    raw_files: list[Any],
    files: list[str],
    rules: list[Rule],
    rules_path: Path,
    meta: dict[str, Any],
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, str]:
    """Process raw file entries; return (file_entries, fails, needs_human, overall_status)."""
    file_entries: list[dict[str, Any]] = []
    fails = 0
    needs_human = 0
    overall_status = "pass"
    expected_paths = set(files)
    for entry in raw_files:
        if not isinstance(entry, dict):
            continue
        result = _entries_process_one(
            entry, rules, rules_path, meta, validate_file_ledger
        )
        if result is None:
            continue
        out_entry, f, nh = result
        expected_paths.discard(out_entry["path"])
        file_entries.append(out_entry)
        fails += f
        needs_human += nh
        overall_status = _merge_status(overall_status, out_entry["status"])
    for missing_path in sorted(expected_paths):
        file_entries.append(_pending_entry(missing_path))
        overall_status = "pending"
    return file_entries, fails, needs_human, overall_status


def validate_index_from_entries(
    *,
    ledger_path: Path,
    files: list[str],
    rules: list[Rule],
    rules_path: Path,
    raw: dict[str, Any],
    meta: dict[str, Any],
    raw_files: list[Any],
    validate_file_ledger: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Validate index ledger from existing file entries (non-sequential)."""
    file_entries, fails, needs_human, overall_status = _process_raw_entries(
        raw_files, files, rules, rules_path, meta, validate_file_ledger
    )
    return _write_index_and_return(
        ledger_path=ledger_path,
        raw=raw,
        meta=meta,
        file_entries=file_entries,
        fails=fails,
        needs_human=needs_human,
        overall_status=overall_status,
    )
