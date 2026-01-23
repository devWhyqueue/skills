from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def filter_python_files(files: Iterable[str]) -> list[str]:
    return [f for f in files if f.endswith(".py") and Path(f).is_file()]


def is_within_dir(path: Path, directory: Path) -> bool:
    resolved_path = path.resolve()
    resolved_dir = directory.resolve()
    return resolved_path.is_relative_to(resolved_dir)


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def count_lines(text: str) -> int:
    return len(text.splitlines())
