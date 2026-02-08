"""Extra tests for semantic.gate (default_semantic_out_dir, reset_semantic_out_dir, run_semantic_gate_if_enabled)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from semantic.gate import (
    default_semantic_out_dir,
    reset_semantic_out_dir,
    run_semantic_gate_if_enabled,
)


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
