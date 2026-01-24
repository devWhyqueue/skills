from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml

from git import current_branch
from .ledger import load_and_validate_ledger
from .prompt import build_index_prompt
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


def run_semantic_gate_if_enabled(
    *,
    enabled: bool,
    files: list[str],
    base_ref: str,
    head_ref: str,
) -> Optional[dict[str, object]]:
    filtered_files = _filter_semantic_files(files)
    if not enabled or not filtered_files:
        return None

    if not SEMANTIC_RULES_PATH.exists():
        raise RuntimeError(
            f"Semantic gate enabled but rules file not found: {SEMANTIC_RULES_PATH}"
        )

    semantic_out_dir = default_semantic_out_dir()

    next_file = _select_next_file(
        files=filtered_files, out_dir=semantic_out_dir, rules_path=SEMANTIC_RULES_PATH
    )
    if next_file is not None:
        semantic_report = run_scaffold(
            base_ref=base_ref,
            head_ref=head_ref,
            files=[next_file],
            rules_path=SEMANTIC_RULES_PATH,
            max_diff_chars=SEMANTIC_MAX_DIFF_CHARS,
            out_dir=semantic_out_dir,
        )
    else:
        semantic_report = {
            "status": "pass",
            "ledger_path": str(semantic_out_dir / "semantic_ledger.yml"),
            "ledger_template_path": str(
                semantic_out_dir / "semantic_ledger.template.yml"
            ),
            "prompt_path": str(semantic_out_dir / "semantic_prompt.md"),
            "summary": {"fails": 0, "needs_human": 0},
            "semantic_rules": [],
        }

    ledger_path = semantic_out_dir / "semantic_ledger.yml"
    semantic_validation = load_and_validate_ledger(
        ledger_path=ledger_path, files=filtered_files, rules_path=SEMANTIC_RULES_PATH
    )
    if next_file is None:
        prompt_path = semantic_out_dir / "semantic_prompt.md"
        prompt_path.write_text(
            build_index_prompt(files_info=[], base_ref=base_ref, head_ref=head_ref),
            encoding="utf-8",
        )
    else:
        _rewrite_index_prompt_for_next_file(
            ledger_path=ledger_path, prompt_path=semantic_out_dir / "semantic_prompt.md"
        )
    return {**semantic_report, **semantic_validation}


def _rewrite_index_prompt_for_next_file(
    *, ledger_path: Path, prompt_path: Path
) -> None:
    if not ledger_path.exists():
        return

    raw_any = yaml.safe_load(
        ledger_path.read_text(encoding="utf-8", errors="replace")
    ) or {}
    raw = raw_any if isinstance(raw_any, dict) else {}
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list):
        return

    if not any(
        isinstance(entry, dict) and isinstance(entry.get("ledger_path"), str)
        for entry in raw_files
    ):
        return

    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    base_ref = str(meta.get("base_ref", "")).strip()
    head_ref = str(meta.get("head_ref", "")).strip()

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
        build_index_prompt(
            files_info=files_info,
            base_ref=base_ref,
            head_ref=head_ref,
        ),
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
