from __future__ import annotations

import os
from pathlib import Path


def default_rules_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "clean_code_rules.yml")


def load_env_file(path: Path) -> None:
    """Load simple `KEY=VALUE` lines into `os.environ` if missing."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value
