from __future__ import annotations

import tempfile
from pathlib import Path
import shutil
from typing import Any, Optional

import yaml

from git import current_branch
from .validate import load_and_validate_ledger
from .scaffold import SEMANTIC_BATCH_SIZE, build_index_prompt, run_scaffold
from .utils import file_has_non_whitespace, safe_slug

SEMANTIC_MAX_DIFF_CHARS = 120_000
SEMANTIC_RULES_PATH = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"


def default_semantic_out_dir() -> Path:
    """
    Use a stable temp directory per git branch so a human/Codex can edit the
    semantic ledger and rerun without losing the file.
    """
    branch = current_branch()
    safe = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in branch
    )
    return Path(tempfile.gettempdir()) / f"clean-code-semantic-{safe}"


def reset_semantic_out_dir() -> Path:
    """Clear and recreate the semantic output directory; return its path."""
    out_dir = default_semantic_out_dir()
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _build_semantic_pass_report(out_dir: Path) -> dict[str, object]:
    """Build the report dict when semantic gate passes (no file to scaffold)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "semantic_ledger.yml"
    ledger_template_path = out_dir / "semantic_ledger.template.yml"
    prompt_path = out_dir / "semantic_prompt.md"
    empty_index = {
        "version": 1,
        "meta": {"phase": "evaluated", "mode": "batched_sequential"},
        "summary": {"fails": 0, "needs_human": 0},
        "files": [],
    }
    ledger_path.write_text(yaml.safe_dump(empty_index, sort_keys=False), encoding="utf-8")
    ledger_template_path.write_text(
        yaml.safe_dump(empty_index, sort_keys=False), encoding="utf-8"
    )
    prompt_path.write_text(build_index_prompt(files_info=[]), encoding="utf-8")
    return {
        "status": "pass",
        "ledger_path": str(ledger_path),
        "ledger_template_path": str(ledger_template_path),
        "prompt_path": str(prompt_path),
        "summary": {"fails": 0, "needs_human": 0},
        "semantic_rules": [],
    }


def _run_scaffold_or_pass(
    *,
    next_files: list[str],
    filtered_files: list[str],
    out_dir: Path,
) -> dict[str, object]:
    """Run scaffold for next_files if any; otherwise return pass report."""
    if next_files:
        return run_scaffold(
            files=next_files,
            rules_path=SEMANTIC_RULES_PATH,
            max_diff_chars=SEMANTIC_MAX_DIFF_CHARS,
            out_dir=out_dir,
        )
    return _build_semantic_pass_report(out_dir)


def _write_index_prompt_after_gate(
    *,
    ledger_path: Path,
    prompt_path: Path,
) -> None:
    """Write index prompt (empty or for next file) after gate run."""
    _rewrite_index_prompt_for_next_batch(
        ledger_path=ledger_path, prompt_path=prompt_path
    )


def run_semantic_gate_if_enabled(
    *,
    enabled: bool,
    files: list[str],
) -> Optional[dict[str, object]]:
    """Run the semantic gate if enabled and files are present; return report or None."""
    filtered_files = _filter_semantic_files(files)
    if not enabled or not filtered_files:
        return None
    if not SEMANTIC_RULES_PATH.exists():
        raise RuntimeError(
            f"Semantic gate enabled but rules file not found: {SEMANTIC_RULES_PATH}"
        )
    out_dir = default_semantic_out_dir()
    next_files = _select_next_files(
        files=filtered_files, out_dir=out_dir, rules_path=SEMANTIC_RULES_PATH
    )
    semantic_report = _run_scaffold_or_pass(
        next_files=next_files, filtered_files=filtered_files, out_dir=out_dir
    )
    if not next_files:
        return semantic_report
    ledger_path = out_dir / "semantic_ledger.yml"
    semantic_validation = load_and_validate_ledger(
        ledger_path=ledger_path, files=filtered_files, rules_path=SEMANTIC_RULES_PATH
    )
    _write_index_prompt_after_gate(
        ledger_path=ledger_path,
        prompt_path=out_dir / "semantic_prompt.md",
    )
    return {**semantic_report, **semantic_validation}


def _rewrite_index_prompt_for_next_batch(
    *, ledger_path: Path, prompt_path: Path
) -> None:
    if not ledger_path.exists():
        return

    raw_any = (
        yaml.safe_load(ledger_path.read_text(encoding="utf-8", errors="replace")) or {}
    )
    raw = raw_any if isinstance(raw_any, dict) else {}
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list):
        return

    if not any(
        isinstance(entry, dict) and isinstance(entry.get("ledger_path"), str)
        for entry in raw_files
    ):
        return

    next_entries = _select_next_file_entries(raw_files)
    files_info: list[dict[str, str]] = [
        {
            "path": str(entry.get("path", "")).strip(),
            "ledger_path": str(entry.get("ledger_path", "")).strip(),
            "prompt_path": str(entry.get("prompt_path", "")).strip(),
        }
        for entry in next_entries
    ]

    prompt_path.write_text(
        build_index_prompt(files_info=files_info),
        encoding="utf-8",
    )


def _select_next_files(
    *, files: list[str], out_dir: Path, rules_path: Path
) -> list[str]:
    ledger_dir = out_dir / "ledgers"
    pending: list[str] = []
    for path in files:
        ledger_path = ledger_dir / f"{safe_slug(path)}.yml"
        if not ledger_path.exists():
            pending.append(path)
            if len(pending) == SEMANTIC_BATCH_SIZE:
                break
            continue
        result = load_and_validate_ledger(
            ledger_path=ledger_path, files=[path], rules_path=rules_path
        )
        status = str(result.get("status", "")).strip().lower()
        if status != "pass":
            pending.append(path)
            if len(pending) == SEMANTIC_BATCH_SIZE:
                break
    return pending


def _filter_semantic_files(files: list[str]) -> list[str]:
    return [path for path in files if file_has_non_whitespace(path)]


def _select_next_file_entries(
    files: list[Any],
) -> list[dict[str, Any]]:
    next_entries: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip().lower()
        if status in {"pending", "requires_reviewer", "fail"}:
            next_entries.append(entry)
            if len(next_entries) == SEMANTIC_BATCH_SIZE:
                break
    return next_entries
