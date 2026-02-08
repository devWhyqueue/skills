"""Tests for cli.env (default_rules_path, load_env_file)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli.env import default_rules_path, load_env_file


def test_default_rules_path() -> None:
    path = default_rules_path()
    assert "clean_code_rules" in path
    assert path.endswith(".yml") or path.endswith(".yaml")


def test_load_env_file_nonexistent(tmp_path: Path) -> None:
    load_env_file(tmp_path / "missing.env")
    # no raise


def test_load_env_file_loads_key_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=my_value\n# comment\n\nOTHER=123\n")
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    load_env_file(env_file)
    assert os.environ.get("MY_KEY") == "my_value"
    assert os.environ.get("OTHER") == "123"


def test_load_env_file_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=overwrite\n")
    monkeypatch.setenv("EXISTING", "keep")
    load_env_file(env_file)
    assert os.environ.get("EXISTING") == "keep"


def test_load_env_file_skips_invalid_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NO_EQUALS\n=only_value\n# comment\nVALID=yes\n")
    monkeypatch.delenv("VALID", raising=False)
    load_env_file(env_file)
    assert os.environ.get("VALID") == "yes"
