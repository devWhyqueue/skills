from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

import vulture_gate.gate as vulture_gate


def _fake_run_success(cmd: List[str]) -> Tuple[int, str, str]:
    return 0, "", ""


def _fake_run_with_issue(cmd: List[str]) -> Tuple[int, str, str]:
    line = "x.py:10: unused function 'foo' (60% confidence)"
    return 3, f"{line}\n", ""


def test_run_vulture_gate_disabled() -> None:
    report, summary, failed = vulture_gate.run_vulture_gate(
        enabled=False, changed_files=["x.py"]
    )
    assert report is None
    assert summary is None
    assert failed is False


def test_run_vulture_gate_no_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["vulture"]

    def _fake_run(
        cmd: List[str], env: Dict[str, Any] | None = None
    ) -> Tuple[int, str, str]:
        _ = env
        return _fake_run_success(cmd)

    monkeypatch.setattr(vulture_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(vulture_gate, "run", _fake_run)
    report, summary, failed = vulture_gate.run_vulture_gate(
        enabled=True, changed_files=["x.py"]
    )
    assert failed is False
    assert summary is None
    assert report is not None
    assert report["issues"] == []


def test_run_vulture_gate_with_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["vulture"]

    def _fake_run(
        cmd: List[str], env: Dict[str, Any] | None = None
    ) -> Tuple[int, str, str]:
        _ = env
        return _fake_run_with_issue(cmd)

    monkeypatch.setattr(vulture_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(vulture_gate, "run", _fake_run)
    report, summary, failed = vulture_gate.run_vulture_gate(
        enabled=True, changed_files=["x.py"]
    )
    assert failed is True
    assert summary == "Vulture detected dead code in changed files."
    assert report is not None
    assert report["exit_code"] == 3
    assert report["issues"] == [
        {
            "file": "x.py",
            "line": 10,
            "name": "foo",
            "type": "function",
            "message": "unused function 'foo'",
        }
    ]

