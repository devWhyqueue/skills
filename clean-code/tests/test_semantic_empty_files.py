from __future__ import annotations

from pathlib import Path

from semantic.gate import _filter_semantic_files


def test_filter_semantic_files_skips_empty_files(tmp_path: Path) -> None:
    empty_file = tmp_path / "__init__.py"
    empty_file.write_text("", encoding="utf-8")

    whitespace_file = tmp_path / "whitespace.py"
    whitespace_file.write_text(" \n\t\n", encoding="utf-8")

    content_file = tmp_path / "module.py"
    content_file.write_text("value = 1\n", encoding="utf-8")

    files = [str(empty_file), str(whitespace_file), str(content_file)]

    assert _filter_semantic_files(files) == [str(content_file)]
