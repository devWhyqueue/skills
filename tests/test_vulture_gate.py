from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

import vulture_gate.gate as vulture_gate


def test_build_vulture_cmd_excludes_dot_dirs_when_scanning_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When scan path is '.', cmd includes --exclude for dot-prefixed dirs (.venv, .git, etc.)."""
    monkeypatch.setattr(vulture_gate, "tool_cmd", lambda _: ["vulture"])
    from vulture_gate.gate import _build_vulture_cmd

    cmd = _build_vulture_cmd(["."])
    # Collect all patterns that follow --exclude
    patterns = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--exclude"]
    assert ".*" in patterns
    assert "*/.?*" in patterns


def test_build_vulture_cmd_excludes_test_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vulture never analyses test code: cmd includes --exclude for test/ and tests/."""
    monkeypatch.setattr(vulture_gate, "tool_cmd", lambda _: ["vulture"])
    from vulture_gate.gate import _build_vulture_cmd

    for scan_paths in [["."], ["src"]]:
        cmd = _build_vulture_cmd(scan_paths)
        patterns = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--exclude"]
        assert "test/*" in patterns
        assert "tests/*" in patterns
        assert "*/test/*" in patterns
        assert "*/tests/*" in patterns


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


def test_run_vulture_gate_issue_outside_changed_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue in a file not in changed_files is filtered out; gate passes."""
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["vulture"]

    def _fake_run(
        cmd: List[str], env: Dict[str, Any] | None = None
    ) -> Tuple[int, str, str]:
        _ = env
        # Vulture reports dead code in other.py; we only changed x.py
        line = "other.py:5: unused function 'bar' (60% confidence)"
        return 3, f"{line}\n", ""

    monkeypatch.setattr(vulture_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(vulture_gate, "run", _fake_run)
    report, summary, failed = vulture_gate.run_vulture_gate(
        enabled=True, changed_files=["x.py"]
    )
    assert failed is False
    assert summary is None
    assert report is not None
    assert report["issues"] == []


def test_run_vulture_gate_issue_in_changed_but_outside_scope_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue in a changed file that is outside package_dir is filtered out."""
    def _fake_tool_cmd(_: str) -> List[str]:
        return ["vulture"]

    def _fake_run(
        cmd: List[str], env: Dict[str, Any] | None = None
    ) -> Tuple[int, str, str]:
        _ = env
        line = "other/pkg.py:5: unused function 'bar' (60% confidence)"
        return 3, f"{line}\n", ""

    monkeypatch.setattr(vulture_gate, "tool_cmd", _fake_tool_cmd)
    monkeypatch.setattr(vulture_gate, "run", _fake_run)
    report, summary, failed = vulture_gate.run_vulture_gate(
        enabled=True,
        changed_files=["other/pkg.py", "src/data_pipelines/dags/abr1/ingestion.py"],
        package_dir=Path("src/data_pipelines"),
    )
    assert failed is False
    assert report is not None
    assert report["issues"] == []

