from __future__ import annotations

import tempfile
from pathlib import Path
import shutil
from typing import Any, Optional

import yaml

from git import current_branch
from .validate import load_and_validate_ledger
from .scaffold import build_index_prompt
from .scaffold import run_scaffold
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
    return {
        "status": "pass",
        "ledger_path": str(out_dir / "semantic_ledger.yml"),
        "ledger_template_path": str(out_dir / "semantic_ledger.template.yml"),
        "prompt_path": str(out_dir / "semantic_prompt.md"),
        "summary": {"fails": 0, "needs_human": 0},
        "semantic_rules": [],
    }


def _run_scaffold_or_pass(
    *,
    next_file: Optional[str],
    filtered_files: list[str],
    out_dir: Path,
) -> dict[str, object]:
    """Run scaffold for next_file if any; otherwise return pass report."""
    if next_file is not None:
        return run_scaffold(
            files=[next_file],
            rules_path=SEMANTIC_RULES_PATH,
            max_diff_chars=SEMANTIC_MAX_DIFF_CHARS,
            out_dir=out_dir,
        )
    return _build_semantic_pass_report(out_dir)


def _write_index_prompt_after_gate(
    *,
    next_file: Optional[str],
    ledger_path: Path,
    prompt_path: Path,
) -> None:
    """Write index prompt (empty or for next file) after gate run."""
    if next_file is None:
        prompt_path.write_text(
            build_index_prompt(files_info=[]),
            encoding="utf-8",
        )
    else:
        _rewrite_index_prompt_for_next_file(
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
    next_file = _select_next_file(
        files=filtered_files, out_dir=out_dir, rules_path=SEMANTIC_RULES_PATH
    )
    semantic_report = _run_scaffold_or_pass(
        next_file=next_file, filtered_files=filtered_files, out_dir=out_dir
    )
    ledger_path = out_dir / "semantic_ledger.yml"
    semantic_validation = load_and_validate_ledger(
        ledger_path=ledger_path, files=filtered_files, rules_path=SEMANTIC_RULES_PATH
    )
    _write_index_prompt_after_gate(
        next_file=next_file,
        ledger_path=ledger_path,
        prompt_path=out_dir / "semantic_prompt.md",
    )
    return {**semantic_report, **semantic_validation}


def _rewrite_index_prompt_for_next_file(
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

    next_entry = _select_next_file_entry(raw_files)
    files_info: list[dict[str, str]] = []
    if isinstance(next_entry, dict):
        files_info.append(
            {
                "path": str(next_entry.get("path", "")).strip(),
                "ledger_path": str(next_entry.get("ledger_path", "")).strip(),
                "prompt_path": str(next_entry.get("prompt_path", "")).strip(),
            }
        )

    prompt_path.write_text(
        build_index_prompt(files_info=files_info),
        encoding="utf-8",
    )


def _select_next_file(
    *, files: list[str], out_dir: Path, rules_path: Path
) -> Optional[str]:
    ledger_dir = out_dir / "ledgers"
    for path in files:
        ledger_path = ledger_dir / f"{safe_slug(path)}.yml"
        if not ledger_path.exists():
            return path
        result = load_and_validate_ledger(
            ledger_path=ledger_path, files=[path], rules_path=rules_path
        )
        status = str(result.get("status", "")).strip().lower()
        if status != "pass":
            return path
    return None


def _filter_semantic_files(files: list[str]) -> list[str]:
    return [path for path in files if file_has_non_whitespace(path)]


def _select_next_file_entry(
    files: list[Any],
) -> Optional[dict[str, Any]]:
    for entry in files:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip().lower()
        if status in {"pending", "requires_reviewer", "fail"}:
            return entry
    return None
