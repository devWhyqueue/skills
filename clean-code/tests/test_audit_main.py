"""Tests for audit.__main__ (main)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from audit.__main__ import main


def test_main_pass_no_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    """main returns 0 when no violations."""
    monkeypatch.setattr(
        "audit.__main__.uncommitted_changed_files", lambda: []
    )
    monkeypatch.setattr(
        "audit.__main__.filter_python_files", lambda x: []
    )
    monkeypatch.setattr(
        "audit.__main__.exclude_test_folders", lambda x: []
    )
    monkeypatch.setattr(
        "audit.__main__.audit_python_files", lambda x: ([], [])
    )
    assert main([]) == 0


def test_main_fail_with_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    """main returns 2 when there are violations."""
    from audit.auditor import Violation

    monkeypatch.setattr(
        "audit.__main__.uncommitted_changed_files", lambda: ["a.py"]
    )
    monkeypatch.setattr(
        "audit.__main__.filter_python_files", lambda x: x
    )
    monkeypatch.setattr(
        "audit.__main__.exclude_test_folders", lambda x: x
    )
    monkeypatch.setattr(
        "audit.__main__.audit_python_files",
        lambda x: (["a.py"], [Violation("r", "a.py", 1, "msg")]),
    )
    assert main([]) == 2


def test_main_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """main with --json parses args and runs (no crash)."""
    monkeypatch.setattr(
        "audit.__main__.uncommitted_changed_files", lambda: []
    )
    monkeypatch.setattr(
        "audit.__main__.filter_python_files", lambda x: []
    )
    monkeypatch.setattr(
        "audit.__main__.exclude_test_folders", lambda x: []
    )
    monkeypatch.setattr(
        "audit.__main__.audit_python_files", lambda x: ([], [])
    )
    assert main(["--json"]) == 0
