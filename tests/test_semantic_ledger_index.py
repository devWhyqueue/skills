from __future__ import annotations

import logging
from pathlib import Path

import yaml

from semantic.ledger import dump_yaml, new_ledger
from semantic.validate import load_and_validate_ledger
from semantic.utils import load_rules, safe_slug

logger = logging.getLogger(__name__)


def _set_all_rules_pass(ledger_path: Path, *, file_path: str, rules_path: Path) -> None:
    rules = load_rules(rules_path)
    ledger = new_ledger(
        rules_path=rules_path,
        files=[file_path],
        rules=rules,
    )
    for file_entry in ledger["files"]:
        for rule_entry in file_entry["rules"]:
            rule_entry["status"] = "PASS"
            rule_entry["evidence"] = [
                {
                    "symbol": "<module>",
                    "lines": {"start": 1, "end": 1},
                    "message": "Reviewed for semantic rule compliance.",
                }
            ]
    ledger_path.write_text(dump_yaml(ledger), encoding="utf-8")


def test_index_ledger_aggregates_per_file_ledgers(tmp_path: Path) -> None:
    """load_and_validate_ledger on an index ledger returns pass when file ledgers pass."""
    rules_path = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
    sample_file = tmp_path / "example.py"
    sample_file.write_text("x = 1\n", encoding="utf-8")

    ledger_dir = tmp_path / "ledgers"
    prompt_dir = tmp_path / "prompts"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    file_ledger = ledger_dir / "example.yml"
    _set_all_rules_pass(file_ledger, file_path=str(sample_file), rules_path=rules_path)

    index_path = tmp_path / "semantic_ledger.yml"
    index_payload = {
        "version": 1,
        "meta": {
            "generated_at_utc": "2024-01-01T00:00:00+00:00",
            "rules_path": rules_path.as_posix(),
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": [
            {
                "path": str(sample_file),
                "ledger_path": file_ledger.as_posix(),
                "prompt_path": (prompt_dir / "example.md").as_posix(),
            }
        ],
    }
    index_path.write_text(
        yaml.safe_dump(index_payload, sort_keys=False), encoding="utf-8"
    )

    result = load_and_validate_ledger(
        ledger_path=index_path, files=[str(sample_file)], rules_path=rules_path
    )

    assert result["status"] == "pass"
    assert result["summary"] == {"fails": 0, "needs_human": 0}


def test_index_ledger_batched_sequential_mode_aggregates_passed_ledgers(
    tmp_path: Path,
) -> None:
    rules_path = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
    sample_file = tmp_path / "batched.py"
    sample_file.write_text("x = 1\n", encoding="utf-8")

    ledger_dir = tmp_path / "ledgers"
    prompt_dir = tmp_path / "prompts"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    file_ledger = ledger_dir / f"{safe_slug(str(sample_file))}.yml"
    _set_all_rules_pass(file_ledger, file_path=str(sample_file), rules_path=rules_path)

    index_path = tmp_path / "semantic_ledger.yml"
    index_payload = {
        "version": 1,
        "meta": {
            "generated_at_utc": "2024-01-01T00:00:00+00:00",
            "rules_path": rules_path.as_posix(),
            "mode": "batched_sequential",
            "ledger_dir": ledger_dir.as_posix(),
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": [
            {
                "path": str(sample_file),
                "ledger_path": file_ledger.as_posix(),
                "prompt_path": (prompt_dir / "batched.md").as_posix(),
            }
        ],
    }
    index_path.write_text(
        yaml.safe_dump(index_payload, sort_keys=False), encoding="utf-8"
    )

    result = load_and_validate_ledger(
        ledger_path=index_path, files=[str(sample_file)], rules_path=rules_path
    )

    assert result["status"] == "pass"
    assert result["summary"] == {"fails": 0, "needs_human": 0}
