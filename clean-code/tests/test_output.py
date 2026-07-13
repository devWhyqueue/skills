"""Tests for concise runner output."""

from __future__ import annotations

import json

from cli.output import MAX_FINDINGS, MAX_LINE_LENGTH, format_report


def _report(**updates: object) -> dict[str, object]:
    report: dict[str, object] = {
        "status": "pass",
        "summary": "All clean code checks passed.",
        "scope": "all",
        "pipeline_mode": "default",
        "changed_files": [],
        "fixed_files": [],
    }
    report.update(updates)
    return report


def test_format_report_pass_is_concise() -> None:
    output = format_report(_report(pyright={"exit_code": 0}), as_json=False)

    assert output.splitlines() == [
        "PASS clean-code | scope=all | mode=default | files=0 | fixed=0",
        "All clean code checks passed.",
        "pyright: pass",
    ]


def test_format_report_limits_findings() -> None:
    findings = [
        {"file": "a.py", "line": index, "rule_id": "CC", "message": "x"}
        for index in range(MAX_FINDINGS + 1)
    ]
    output = format_report(_report(status="fail", violations=findings), as_json=False)

    assert "stage=audit" in output
    assert "1 additional findings" in output


def test_format_report_truncates_pytest_output() -> None:
    long_line = "x" * (MAX_LINE_LENGTH + 1)
    report = _report(status="fail", pytest={"exit_code": 1, "stdout": long_line})

    output = format_report(report, as_json=False)

    assert "stage=pytest" in output
    assert "…" in output


def test_format_report_json_preserves_raw_data() -> None:
    report = _report(pyright={"exit_code": 1, "stdout": "details"})

    output = format_report(report, as_json=True)

    assert json.loads(output) == report


def test_vulture_exit_three_does_not_hide_later_failure() -> None:
    """Treat Vulture's non-actionable findings status as a passing stage."""
    report = _report(
        status="fail",
        vulture={"exit_code": 3, "issues": []},
        pytest={"exit_code": 1, "stdout": "failed test"},
    )

    output = format_report(report, as_json=False)

    assert "stage=pytest" in output
