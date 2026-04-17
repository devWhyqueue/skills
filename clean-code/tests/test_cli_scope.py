"""Tests for cli.scope."""
from __future__ import annotations

from pathlib import Path

import pytest

from cli.scope import (
    derive_scope_from_files,
    find_package_root,
    normalize_package_value,
    resolve_package_dir,
)


def test_derive_scope_from_files_empty() -> None:
    assert derive_scope_from_files([]) == "core"


def test_derive_scope_from_files_single_src() -> None:
    assert derive_scope_from_files(["src/etl/foo.py"]) == "etl"


def test_derive_scope_from_files_multi() -> None:
    assert derive_scope_from_files(["src/etl/a.py", "src/report/b.py"]) == "multi"


def test_derive_scope_from_files_single_part() -> None:
    assert derive_scope_from_files(["cli/runner.py"]) == "cli"


def test_normalize_package_value_empty() -> None:
    assert normalize_package_value("") == ""
    assert normalize_package_value("   ") == ""


def test_normalize_package_value_dots() -> None:
    assert normalize_package_value("a.b.c") == "a/b/c"


def test_normalize_package_value_slashes() -> None:
    assert normalize_package_value("src/etl") == "src/etl"
    assert normalize_package_value("\\src\\etl\\") == "src/etl"


def test_find_package_root_no_init(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("")
    assert find_package_root(tmp_path / "foo.py") is None


def test_find_package_root_has_init(tmp_path: Path) -> None:
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "x.py").write_text("")
    assert find_package_root(pkg / "x.py") == pkg


def test_resolve_package_dir_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        resolve_package_dir("")
    with pytest.raises(ValueError, match="non-empty"):
        resolve_package_dir("   ")


def test_resolve_package_dir_existing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "src" / "etl"
    d.mkdir(parents=True)
    result = resolve_package_dir("etl")
    assert result == Path("src/etl")


def test_resolve_package_dir_via_git_ls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_try_candidate_dirs(normalized: str) -> None:
        return None

    def _fake_git_ls_files() -> list[str]:
        return ["src/cli/__init__.py"]

    from cli import scope as scope_mod
    monkeypatch.setattr(scope_mod, "_try_candidate_dirs", _fake_try_candidate_dirs)
    monkeypatch.setattr(scope_mod, "git_ls_files", _fake_git_ls_files)
    result = resolve_package_dir("cli")
    assert result == Path("src/cli")


def test_resolve_package_dir_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_git_run(cmd: list) -> object:
        return type("R", (), {"returncode": 0, "stdout": ""})()

    def _try_candidate_dirs(normalized: str) -> None:
        return None

    from cli import scope as scope_mod
    monkeypatch.setattr(scope_mod, "git_run", _fake_git_run)
    monkeypatch.setattr(scope_mod, "_try_candidate_dirs", lambda _: None)
    monkeypatch.setattr(scope_mod, "_resolve_via_ls_files", lambda _: [])
    with pytest.raises(RuntimeError, match="Could not resolve"):
        resolve_package_dir("nonexistent")
