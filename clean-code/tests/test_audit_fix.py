"""Tests for audit.fix (ensure_logger_scaffold, replace_print_with_logger, fix_files, run, tool_cmd)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audit.fix import (
    FixResult,
    ensure_logger_scaffold,
    fix_files,
    replace_print_with_logger,
    run,
    tool_cmd,
)


def test_run_success() -> None:
    code, out, err = run([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert "ok" in out


def test_run_failure() -> None:
    code, out, err = run([sys.executable, "-c", "raise SystemExit(1)"])
    assert code == 1


def test_tool_cmd_ruff_like() -> None:
    # tool_cmd looks for sibling of sys.executable (e.g. ruff.exe next to python.exe)
    try:
        cmd = tool_cmd("ruff")
        assert isinstance(cmd, list)
        assert len(cmd) == 1
    except RuntimeError as e:
        assert "Missing required tool" in str(e)


def test_ensure_logger_scaffold_no_print() -> None:
    source = "x = 1\n"
    assert ensure_logger_scaffold(source) == source


def test_ensure_logger_scaffold_adds_import_and_logger() -> None:
    source = 'print("x")\n'
    out = ensure_logger_scaffold(source)
    assert "import logging" in out
    assert "logger = logging.getLogger(__name__)" in out


def test_ensure_logger_scaffold_after_docstring() -> None:
    source = '"""Doc."""\nprint("x")\n'
    out = ensure_logger_scaffold(source)
    assert "import logging" in out


def test_replace_print_with_logger() -> None:
    source = 'print("hello")\n'
    out = replace_print_with_logger(source)
    assert "logger.info(" in out
    assert "hello" in out


def test_replace_print_with_logger_comment_unchanged() -> None:
    source = '# print("x")\n'
    out = replace_print_with_logger(source)
    assert out.strip() == '# print("x")'


def test_fix_files_nonexistent() -> None:
    results = fix_files(["/nonexistent/file.py"])
    assert results == []


def test_fix_files_empty_list() -> None:
    results = fix_files([])
    assert results == []


def test_fix_files_print_replaced(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text('"""X."""\nprint("hi")\n')
    with patch("audit.fix.has_ruff", return_value=False):
        results = fix_files([str(p)])
    assert len(results) == 1
    assert results[0].file == str(p)
    assert results[0].changed is True
    assert "replace_print_with_logger" in results[0].actions
    assert "logger.info" in p.read_text()


def test_ruff_called_on_all_changed_set_files(tmp_path: Path) -> None:
    """ruff_fix_and_format receives every file in the changed set, not just fix-modified ones."""
    changed = tmp_path / "changed.py"
    unchanged = tmp_path / "unchanged.py"
    changed.write_text('"""M."""\nprint("hi")\n', newline="\n")
    unchanged.write_text('x = 1\n', newline="\n")

    ruff_received: list[list[str]] = []

    def _capture_ruff(files: list[str]) -> None:
        ruff_received.append(list(files))

    with patch("audit.fix.ruff_fix_and_format", side_effect=_capture_ruff):
        results = fix_files([str(changed), str(unchanged)])

    assert len(results) == 2
    assert results[0].changed is True
    assert results[1].changed is False

    assert len(ruff_received) == 1
    assert ruff_received[0] == [str(changed), str(unchanged)]


def test_fix_result_dataclass() -> None:
    r = FixResult(file="f.py", changed=True, actions=["a"])
    assert r.file == "f.py"
    assert r.changed is True
    assert r.actions == ["a"]
