"""Tests for git.uncommitted_changed_files and diff_for_file_uncommitted."""

from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from git import (
    _parse_porcelain_status,
    current_branch,
    diff_for_file_uncommitted,
    run as git_run,
    status_entries,
    uncommitted_changed_files,
)


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


def test_run_returns_completed_process() -> None:
    """run() returns CompletedProcess without raising on non-zero exit."""
    p = git_run([__import__("sys").executable, "-c", "raise SystemExit(2)"])
    assert p.returncode == 2
    p2 = git_run([__import__("sys").executable, "-c", "print(1)"])
    assert p2.returncode == 0
    assert "1" in (p2.stdout or "")


def test_current_branch_unknown_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """current_branch returns 'unknown' when git fails."""
    def _run_fail(cmd: list[str]) -> str:
        raise RuntimeError("not a repo")

    monkeypatch.setattr("git._run", _run_fail)
    assert current_branch() == "unknown"


def test_current_branch_unknown_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """current_branch returns 'unknown' when rev-parse returns empty."""
    monkeypatch.setattr("git._run", lambda cmd: "")
    assert current_branch() == "unknown"


def test_current_branch_returns_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """current_branch returns stripped branch name."""
    monkeypatch.setattr("git._run", lambda cmd: "  main  ")
    assert current_branch() == "main"


def test_parse_porcelain_status_empty() -> None:
    assert _parse_porcelain_status("") == []


def test_parse_porcelain_status_one_entry() -> None:
    # format: status + space + path, null-separated
    out = " M foo.py\0"
    assert _parse_porcelain_status(out) == [(" M", "foo.py")]


def test_parse_porcelain_status_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """status_entries can be called with run mocked to return rename output."""
    def _run(cmd: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(
            cmd, returncode=0,
            stdout="R  old.py\0new.py\0",
            stderr="",
        )

    monkeypatch.setattr("git.run", _run)
    entries = status_entries()
    assert len(entries) >= 1
