from __future__ import annotations

from pathlib import Path
from typing import Any

from git import diff_for_file
from semantic.ledger import dump_yaml, new_ledger, normalize_ledger
from semantic.prompt import build_file_prompt, build_index_prompt
from semantic.rules import load_rules
from semantic.utils import posix, safe_slug, truncate, utc_now_iso


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

    ledger_dir = out_dir / "ledgers"
    prompt_dir = out_dir / "prompts"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    files_info: list[dict[str, str]] = []
    for path in files:
        slug = safe_slug(path)
        file_ledger_path = ledger_dir / f"{slug}.yml"
        file_prompt_path = prompt_dir / f"{slug}.md"

        file_prompt_path.write_text(
            build_file_prompt(
                rules=rules,
                path=path,
                diff=diffs.get(path, ""),
                base_ref=base_ref,
                head_ref=head_ref,
            ),
            encoding="utf-8",
        )

        file_ledger = new_ledger(
            rules_path=rules_path,
            base_ref=base_ref,
            head_ref=head_ref,
            files=[path],
            rules=rules,
        )
        file_normalized = normalize_ledger(
            ledger=file_ledger, files=[path], rules=rules
        )
        file_normalized["meta"] = file_ledger["meta"]
        if not file_ledger_path.exists():
            file_ledger_path.write_text(dump_yaml(file_normalized), encoding="utf-8")

        files_info.append(
            {
                "path": path,
                "ledger_path": posix(file_ledger_path),
                "prompt_path": posix(file_prompt_path),
            }
        )

    index_ledger = {
        "version": 1,
        "meta": {
            "generated_at_utc": utc_now_iso(),
            "rules_path": posix(rules_path),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "mode": "single_file",
            "ledger_dir": posix(ledger_dir),
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": files_info,
    }

    prompt_path.write_text(
        build_index_prompt(
            files_info=files_info,
            base_ref=base_ref,
            head_ref=head_ref,
        ),
        encoding="utf-8",
    )
    ledger_template_path.write_text(dump_yaml(index_ledger), encoding="utf-8")
    ledger_path.write_text(dump_yaml(index_ledger), encoding="utf-8")

    return {
        "status": "scaffolded",
        "ledger_path": posix(ledger_path),
        "ledger_template_path": posix(ledger_template_path),
        "prompt_path": posix(prompt_path),
        "summary": index_ledger["summary"],
        "semantic_rules": [{"id": r.id, "statement": r.statement} for r in rules],
    }
