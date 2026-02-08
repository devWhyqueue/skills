"""Extra tests for semantic.scaffold (build_file_prompt, build_index_prompt)."""
from __future__ import annotations

from pathlib import Path

import pytest

from semantic.scaffold import build_file_prompt, build_index_prompt
from semantic.utils import load_rules, Rule


def test_build_index_prompt_empty() -> None:
    out = build_index_prompt(files_info=[])
    assert "all files reviewed" in out.lower() or "(all" in out


def test_build_index_prompt_with_files() -> None:
    files_info = [
        {"path": "a.py", "ledger_path": "ledgers/a.yml", "prompt_path": "prompts/a.md"},
    ]
    out = build_index_prompt(files_info=files_info)
    assert "a.py" in out
    assert "ledgers/a.yml" in out


def test_build_file_prompt(rules_path: Path) -> None:
    rules = load_rules(rules_path)
    out = build_file_prompt(rules=rules, path="x.py", diff="--- a/x.py\n+++ b/x.py\n")
    assert "x.py" in out
    assert "Diff" in out or "diff" in out
    assert "SEMANTIC" in out or "semantic" in out


@pytest.fixture
def rules_path() -> Path:
    return Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
