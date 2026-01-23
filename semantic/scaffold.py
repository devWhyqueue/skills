from __future__ import annotations

from pathlib import Path
from typing import Any

from git import diff_for_file
from semantic.ledger import dump_yaml, new_ledger, normalize_ledger
from semantic.prompt import build_prompt
from semantic.rules import load_rules
from semantic.utils import posix, truncate


def run_scaffold(
    *,
    base_ref: str,
    head_ref: str,
    files: list[str],
    rules_path: Path,
    out_dir: Path,
    max_diff_chars: int = 120_000,
) -> dict[str, Any]:
    rules = load_rules(rules_path)
    diffs = {
        path: truncate(
            diff_for_file(base_ref, head_ref, path), max_chars=max_diff_chars
        )
        for path in files
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "semantic_ledger.yml"
    ledger_template_path = out_dir / "semantic_ledger.template.yml"
    prompt_path = out_dir / "semantic_prompt.md"

    prompt_path.write_text(
        build_prompt(
            rules=rules,
            files=files,
            diffs=diffs,
            base_ref=base_ref,
            head_ref=head_ref,
        ),
        encoding="utf-8",
    )

    ledger = new_ledger(
        rules_path=rules_path,
        base_ref=base_ref,
        head_ref=head_ref,
        files=files,
        rules=rules,
    )

    normalized = normalize_ledger(ledger=ledger, files=files, rules=rules)
    normalized["meta"] = ledger["meta"]

    ledger_template_path.write_text(dump_yaml(normalized), encoding="utf-8")
    if not ledger_path.exists():
        ledger_path.write_text(dump_yaml(normalized), encoding="utf-8")

    return {
        "status": "scaffolded",
        "ledger_path": posix(ledger_path),
        "ledger_template_path": posix(ledger_template_path),
        "prompt_path": posix(prompt_path),
        "summary": normalized["summary"],
        "semantic_rules": [{"id": r.id, "statement": r.statement} for r in rules],
    }
