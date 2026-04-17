from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def filter_python_files(files: Iterable[str]) -> list[str]:
    """Keep only paths that are .py files and exist on disk."""
    return [f for f in files if f.endswith(".py") and Path(f).is_file()]


def exclude_test_folders(files: Iterable[str]) -> list[str]:
    """Drop paths that lie under a 'test' or 'tests' directory segment."""
    result = []
    for f in files:
        parts = Path(f).parts
        if "test" in parts or "tests" in parts:
            continue
        result.append(f)
    return result


def is_within_dir(path: Path, directory: Path) -> bool:
    """Return True if path is under directory (or equal)."""
    resolved_path = path.resolve()
    resolved_dir = directory.resolve()
    return resolved_path.is_relative_to(resolved_dir)


def read_text(path: str | Path) -> str:
    """Read file as UTF-8 text; replace invalid bytes."""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def count_lines(text: str) -> int:
    """Return number of lines in text (by newline split)."""
    return len(text.splitlines())
