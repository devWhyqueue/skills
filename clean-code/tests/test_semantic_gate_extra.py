"""Extra tests for semantic.gate (default_semantic_out_dir, reset_semantic_out_dir, run_semantic_gate_if_enabled)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from semantic.gate import (
    SEMANTIC_BATCH_SIZE,
    default_semantic_out_dir,
    reset_semantic_out_dir,
    run_semantic_gate_if_enabled,
)
from semantic.ledger import dump_yaml, new_ledger
from semantic.utils import load_rules, safe_slug


def test_default_semantic_out_dir() -> None:
    with patch("semantic.gate.current_branch", return_value="main"):
        out = default_semantic_out_dir()
    assert "clean-code-semantic" in str(out)
    assert "main" in str(out)


def test_default_semantic_out_dir_sanitizes_branch() -> None:
    with patch("semantic.gate.current_branch", return_value="feature/foo-bar"):
        out = default_semantic_out_dir()
    assert "clean-code-semantic" in str(out)


def test_reset_semantic_out_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("semantic.gate.default_semantic_out_dir", lambda: tmp_path / "sem")
    (tmp_path / "sem").mkdir()
    (tmp_path / "sem" / "f").write_text("x")
    result = reset_semantic_out_dir()
    assert result == tmp_path / "sem"
    assert result.exists()
    assert not (result / "f").exists()


def test_run_semantic_gate_if_enabled_disabled() -> None:
    assert run_semantic_gate_if_enabled(enabled=False, files=["a.py"]) is None


def test_run_semantic_gate_if_enabled_no_files() -> None:
    assert run_semantic_gate_if_enabled(enabled=True, files=[]) is None


def test_run_semantic_gate_if_enabled_filtered_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All files filtered out (e.g. empty) -> None."""
    monkeypatch.setattr("semantic.gate.file_has_non_whitespace", lambda p: False)
    assert run_semantic_gate_if_enabled(enabled=True, files=["empty.py"]) is None


def _set_all_rules_pass(ledger_path: Path, *, file_path: str, rules_path: Path) -> None:
    rules = load_rules(rules_path)
    ledger = new_ledger(rules_path=rules_path, files=[file_path], rules=rules)
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


def test_run_semantic_gate_scaffolds_up_to_batch_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "semantic"
    files = []
    for idx in range(SEMANTIC_BATCH_SIZE + 2):
        file_path = tmp_path / f"f{idx}.py"
        file_path.write_text(f"x_{idx} = {idx}\n", encoding="utf-8")
        files.append(str(file_path))

    monkeypatch.setattr("semantic.gate.default_semantic_out_dir", lambda: out_dir)
    monkeypatch.setattr("semantic.gate.file_has_non_whitespace", lambda p: True)

    report = run_semantic_gate_if_enabled(enabled=True, files=files)

    assert isinstance(report, dict)
    ledger = yaml.safe_load((out_dir / "semantic_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["meta"]["mode"] == "batched_sequential"
    assert len(ledger["files"]) == SEMANTIC_BATCH_SIZE
    assert [entry["path"] for entry in ledger["files"]] == files[:SEMANTIC_BATCH_SIZE]
    prompt = (out_dir / "semantic_prompt.md").read_text(encoding="utf-8")
    assert files[0] in prompt
    assert files[SEMANTIC_BATCH_SIZE - 1] in prompt
    assert files[SEMANTIC_BATCH_SIZE] not in prompt


def test_run_semantic_gate_advances_to_next_batch_after_passed_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "semantic"
    rules_path = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
    files = []
    for idx in range(SEMANTIC_BATCH_SIZE + 2):
        file_path = tmp_path / f"g{idx}.py"
        file_path.write_text(f"y_{idx} = {idx}\n", encoding="utf-8")
        files.append(str(file_path))

    ledger_dir = out_dir / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    for path in files[:SEMANTIC_BATCH_SIZE]:
        ledger_path = ledger_dir / f"{safe_slug(path)}.yml"
        _set_all_rules_pass(ledger_path, file_path=path, rules_path=rules_path)

    monkeypatch.setattr("semantic.gate.default_semantic_out_dir", lambda: out_dir)
    monkeypatch.setattr("semantic.gate.file_has_non_whitespace", lambda p: True)

    report = run_semantic_gate_if_enabled(enabled=True, files=files)

    assert isinstance(report, dict)
    ledger = yaml.safe_load((out_dir / "semantic_ledger.yml").read_text(encoding="utf-8"))
    assert len(ledger["files"]) == len(files)
    assert all(entry["status"] == "pass" for entry in ledger["files"][:SEMANTIC_BATCH_SIZE])
    remaining = files[SEMANTIC_BATCH_SIZE:]
    prompt = (out_dir / "semantic_prompt.md").read_text(encoding="utf-8")
    assert remaining[0] in prompt
    assert remaining[-1] in prompt
    assert files[0] not in prompt


def test_run_semantic_gate_shows_smaller_remaining_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "semantic"
    rules_path = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
    files = []
    for idx in range(3):
        file_path = tmp_path / f"h{idx}.py"
        file_path.write_text(f"z_{idx} = {idx}\n", encoding="utf-8")
        files.append(str(file_path))

    ledger_dir = out_dir / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    _set_all_rules_pass(
        ledger_dir / f"{safe_slug(files[0])}.yml",
        file_path=files[0],
        rules_path=rules_path,
    )

    monkeypatch.setattr("semantic.gate.default_semantic_out_dir", lambda: out_dir)
    monkeypatch.setattr("semantic.gate.file_has_non_whitespace", lambda p: True)

    run_semantic_gate_if_enabled(enabled=True, files=files)

    ledger = yaml.safe_load((out_dir / "semantic_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["files"][0]["status"] == "pass"
    prompt = (out_dir / "semantic_prompt.md").read_text(encoding="utf-8")
    assert files[1] in prompt
    assert files[2] in prompt
    assert files[0] not in prompt


def test_run_semantic_gate_returns_pass_when_all_ledgers_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "semantic"
    rules_path = Path(__file__).resolve().parent.parent / "clean_code_rules.yml"
    files = []
    ledger_dir = out_dir / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(2):
        file_path = tmp_path / f"p{idx}.py"
        file_path.write_text(f"done_{idx} = {idx}\n", encoding="utf-8")
        files.append(str(file_path))
        _set_all_rules_pass(
            ledger_dir / f"{safe_slug(str(file_path))}.yml",
            file_path=str(file_path),
            rules_path=rules_path,
        )

    monkeypatch.setattr("semantic.gate.default_semantic_out_dir", lambda: out_dir)
    monkeypatch.setattr("semantic.gate.file_has_non_whitespace", lambda p: True)

    report = run_semantic_gate_if_enabled(enabled=True, files=files)

    assert isinstance(report, dict)
    assert report["status"] == "pass"
    prompt = (out_dir / "semantic_prompt.md").read_text(encoding="utf-8")
    assert "all files reviewed" in prompt.lower()
