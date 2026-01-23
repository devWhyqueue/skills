from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from git import current_branch
from semantic import load_and_validate_ledger, run_scaffold

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
    if not enabled or not files:
        return None

    if not SEMANTIC_RULES_PATH.exists():
        raise RuntimeError(
            f"Semantic gate enabled but rules file not found: {SEMANTIC_RULES_PATH}"
        )

    semantic_out_dir = default_semantic_out_dir()

    semantic_report = run_scaffold(
        base_ref=base_ref,
        head_ref=head_ref,
        files=files,
        rules_path=SEMANTIC_RULES_PATH,
        max_diff_chars=SEMANTIC_MAX_DIFF_CHARS,
        out_dir=semantic_out_dir,
    )

    ledger_path = semantic_out_dir / "semantic_ledger.yml"
    semantic_validation = load_and_validate_ledger(
        ledger_path=ledger_path, files=files, rules_path=SEMANTIC_RULES_PATH
    )
    return {**semantic_report, **semantic_validation}
