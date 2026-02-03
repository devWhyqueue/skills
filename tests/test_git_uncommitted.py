"""Tests for git.uncommitted_changed_files and diff_for_file_uncommitted."""

from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from git import diff_for_file_uncommitted, uncommitted_changed_files


def test_uncommitted_changed_files_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no diff and no status entries, result is empty."""
    def _run(_cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(_cmd, returncode=0, stdout="", stderr="")

    def _status_entries() -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr("git.run", _run)
    monkeypatch.setattr("git.status_entries", _status_entries)
    assert uncommitted_changed_files() == []


def test_uncommitted_changed_files_one_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With one modified file in diff, result lists that file."""
    def _run(_cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(_cmd, returncode=0, stdout="bar.py\n", stderr="")

    def _status_entries() -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr("git.run", _run)
    monkeypatch.setattr("git.status_entries", _status_entries)
    assert uncommitted_changed_files() == ["bar.py"]


def test_uncommitted_changed_files_one_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With one untracked file in status, result lists that file."""
    def _run(_cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(_cmd, returncode=0, stdout="", stderr="")

    def _status_entries() -> list[tuple[str, str]]:
        return [("??", "new.py")]

    monkeypatch.setattr("git.run", _run)
    monkeypatch.setattr("git.status_entries", _status_entries)
    assert uncommitted_changed_files() == ["new.py"]


def test_uncommitted_changed_files_modified_and_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With modified and untracked files, result contains both."""
    def _run(_cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(_cmd, returncode=0, stdout="bar.py\n", stderr="")

    def _status_entries() -> list[tuple[str, str]]:
        return [("??", "new.py")]

    monkeypatch.setattr("git.run", _run)
    monkeypatch.setattr("git.status_entries", _status_entries)
    result = uncommitted_changed_files()
    assert sorted(result) == ["bar.py", "new.py"]


def test_diff_for_file_uncommitted_returns_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uncommitted diff returns command stdout when returncode is 0."""
    def _run(cmd: list[str]) -> CompletedProcess[str]:
        assert cmd[:4] == ["git", "diff", "--unified=3", "HEAD"]
        assert cmd[-2:] == ["--", "foo.py"]
        return CompletedProcess(
            cmd, returncode=0, stdout="--- a/foo.py\n+++ b/foo.py\n", stderr=""
        )

    monkeypatch.setattr("git.run", _run)
    assert "foo.py" in diff_for_file_uncommitted("foo.py")


def test_diff_for_file_uncommitted_returns_empty_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On non-zero exit, uncommitted diff returns empty string."""
    def _run(cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(cmd, returncode=1, stdout="", stderr="error")

    monkeypatch.setattr("git.run", _run)
    assert diff_for_file_uncommitted("missing.py") == ""
