"""Tests for audit.files."""
from __future__ import annotations

from pathlib import Path

import pytest

from audit.files import (
    count_lines,
    exclude_test_folders,
    filter_python_files,
    is_within_dir,
    read_text,
)


def test_filter_python_files_only_py() -> None:
    assert filter_python_files(["a.py", "b.txt", "c.py"]) != ["a.py", "b.txt", "c.py"]
    # Without existing files we get [] because Path(f).is_file() is False
    result = filter_python_files([])
    assert result == []


def test_filter_python_files_existing(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("")
    (tmp_path / "y.txt").write_text("")
    files = [str(tmp_path / "x.py"), str(tmp_path / "y.txt")]
    assert filter_python_files(files) == [str(tmp_path / "x.py")]


def test_exclude_test_folders() -> None:
    assert exclude_test_folders(["src/foo.py", "tests/a.py"]) == ["src/foo.py"]
    assert exclude_test_folders(["src/test/bar.py"]) == []
    assert exclude_test_folders(["cli/runner.py"]) == ["cli/runner.py"]


def test_is_within_dir() -> None:
    base = Path("cli")
    assert is_within_dir(Path("cli/runner.py"), base) is True
    assert is_within_dir(Path("audit/foo.py"), base) is False


def test_read_text(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("hello\nworld", encoding="utf-8")
    assert read_text(f) == "hello\nworld"


def test_count_lines() -> None:
    assert count_lines("") == 0
    assert count_lines("a\nb\nc") == 3
