"""Tests for pytest_gate.gate."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

import pytest_gate.gate as pytest_gate


def test_cov_modules_from_changed_files_empty() -> None:
    assert pytest_gate._cov_modules_from_changed_files([]) == []


def test_cov_modules_from_changed_files_single() -> None:
    assert pytest_gate._cov_modules_from_changed_files(["src/etl/foo.py"]) == ["etl.foo"]


def test_cov_modules_from_changed_files_dedupe() -> None:
    assert pytest_gate._cov_modules_from_changed_files(
        ["src/etl/foo.py", "src/etl/bar.py", "src/report/baz.py"]
    ) == ["etl.bar", "etl.foo", "report.baz"]


def test_cov_modules_from_changed_files_skips_non_py() -> None:
    assert pytest_gate._cov_modules_from_changed_files(["cli/runner.py", "readme.md"]) == [
        "cli.runner",
    ]


def test_cov_modules_from_changed_files_skips_tests() -> None:
    assert pytest_gate._cov_modules_from_changed_files(
        ["tests/test_runner.py", "src/pkg/tests/test_helper.py", "src/pkg/module.py"]
    ) == ["pkg.module"]


def test_cov_modules_from_changed_files_skips_init() -> None:
    """__init__.py is excluded so empty package inits do not drag down coverage."""
    assert pytest_gate._cov_modules_from_changed_files(["audit/__init__.py"]) == []


def test_cov_modules_from_changed_files_init_and_other() -> None:
    """When both __init__.py and other files change, only non-init modules are included."""
    assert pytest_gate._cov_modules_from_changed_files(
        ["sonar/__init__.py", "sonar/gate.py"]
    ) == ["sonar.gate"]


def test_parse_coverage_pct_empty() -> None:
    assert pytest_gate._parse_coverage_pct("") is None


def test_parse_coverage_pct_total_line() -> None:
    assert pytest_gate._parse_coverage_pct("TOTAL   92%\n") == 92.0
    assert pytest_gate._parse_coverage_pct("TOTAL 31.64%\n") == 31.64


def test_parse_coverage_pct_from_multiline() -> None:
    out = "foo\nbar\nTOTAL  85%\n"
    assert pytest_gate._parse_coverage_pct(out) == 85.0


def test_parse_coverage_pct_fallback_on_failure_line() -> None:
    """When pytest-cov fails, it prints 'Total coverage: xx%'; we still parse it."""
    out = "FAIL Required test coverage of 90% not reached. Total coverage: 85.23%\n"
    assert pytest_gate._parse_coverage_pct(out) == 85.23


def test_pytest_report_dict_success_with_coverage() -> None:
    r = pytest_gate._pytest_report_dict(0, "out", "err", 95.0, "/path/coverage.xml")
    assert r["exit_code"] == 0
    assert r["coverage_pct"] == 95.0
    assert "95" in r["summary"]


def test_pytest_report_dict_success_no_coverage() -> None:
    r = pytest_gate._pytest_report_dict(0, "out", "err", None, None)
    assert r["summary"] == "All tests passed."


def test_pytest_report_dict_no_tests_collected() -> None:
    r = pytest_gate._pytest_report_dict(
        pytest_gate.PYTEST_EXIT_NO_TESTS_COLLECTED, "out", "err", None, None
    )
    assert r["summary"] == "No tests collected."


def test_pytest_report_dict_failed() -> None:
    r = pytest_gate._pytest_report_dict(1, "out", "err", 50.0, None)
    assert r["summary"] == "Tests failed or coverage below threshold."


def test_run_pytest_gate_disabled() -> None:
    report, summary, failed = pytest_gate.run_pytest_gate(
        enabled=False, changed_files=["x.py"]
    )
    assert report is None
    assert summary is None
    assert failed is False


def test_run_pytest_gate_no_tests_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    """No tests collected is treated as pass; report still reflects it."""
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["pytest"]

    def _fake_run(cmd: List[str], env: Any = None) -> Tuple[int, str, str]:
        return pytest_gate.PYTEST_EXIT_NO_TESTS_COLLECTED, "", ""

    monkeypatch.setattr(pytest_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(pytest_gate, "run", _fake_run)
    report, summary, failed = pytest_gate.run_pytest_gate(
        enabled=True, changed_files=["src/foo.py"]
    )
    assert failed is False
    assert summary is None
    assert report is not None
    assert report["summary"] == "No tests collected."
    assert report["exit_code"] == pytest_gate.PYTEST_EXIT_NO_TESTS_COLLECTED


def test_run_pytest_gate_success_with_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["pytest"]

    def _fake_run(cmd: List[str], env: Any = None) -> Tuple[int, str, str]:
        return 0, "TOTAL  92%\n", ""

    monkeypatch.setattr(pytest_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(pytest_gate, "run", _fake_run)
    report, summary, failed = pytest_gate.run_pytest_gate(
        enabled=True, changed_files=["src/etl/foo.py"]
    )
    assert failed is False
    assert summary is None
    assert report is not None
    assert report["coverage_pct"] == 92.0
    assert report["exit_code"] == 0


def test_run_pytest_gate_exit_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["pytest"]

    def _fake_run(cmd: List[str], env: Any = None) -> Tuple[int, str, str]:
        return 1, "", "some error"

    monkeypatch.setattr(pytest_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(pytest_gate, "run", _fake_run)
    report, summary, failed = pytest_gate.run_pytest_gate(
        enabled=True, changed_files=["x.py"]
    )
    assert failed is True
    assert report is not None
    assert report["exit_code"] == 1


def test_build_pytest_cmd_no_changed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["pytest"]

    monkeypatch.setattr(pytest_gate, "tool_cmd", _fake_tool_cmd)
    cmd, path = pytest_gate._build_pytest_cmd([], 90)
    assert "pytest" in cmd
    assert "--capture=no" in cmd
    assert "--cov" not in cmd
    assert path is None


def test_build_pytest_cmd_with_changed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["pytest"]

    monkeypatch.setattr(pytest_gate, "tool_cmd", _fake_tool_cmd)
    cmd, path = pytest_gate._build_pytest_cmd(["src/a/foo.py", "src/b/bar.py"], 90)
    assert "--capture=no" in cmd
    assert "--cov" in cmd
    # Coverage restricted to changed files (module names)
    assert "a.foo" in cmd
    assert "b.bar" in cmd
    assert "xml:coverage.xml" in cmd
    assert "--cov-fail-under=90" in cmd
    assert path is not None
    assert "coverage.xml" in path
