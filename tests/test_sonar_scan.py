"""Tests for sonar.scan (_venv_tool_cmd, run_scan)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import sonar.scan as scan_mod


def test_venv_tool_cmd_pysonar() -> None:
    """pysonar is resolved to python -c bootstrap."""
    cmd = scan_mod._venv_tool_cmd("pysonar")
    assert cmd[0] == sys.executable
    assert cmd[1] == "-c"
    assert "pysonar" in cmd[2] or "main" in cmd[2]


def test_run_scan_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scan builds env and cmd and returns CompletedProcess."""
    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    result = scan_mod.run_scan("token", "main")
    assert result.returncode == 0


def test_run_scan_with_pr_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scan adds PR props when pull_request_key is set."""
    seen_cmd: list = []

    def _run(cmd, **kwargs):
        seen_cmd.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    scan_mod.run_scan(
        "token", "main",
        pull_request_key="42",
        pull_request_branch="feature",
        pull_request_base="develop",
    )
    assert any("sonar.pullrequest.key" in str(c) for c in seen_cmd)


def test_run_scan_adds_default_props(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scan appends default -D props when not in read_project_properties."""
    seen_cmd: list = []

    def _run(cmd, **kwargs):
        seen_cmd.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    scan_mod.run_scan("token", "main")
    assert any("sonar.sourceEncoding" in str(c) for c in seen_cmd)
    assert any("sonar.scm.provider" in str(c) for c in seen_cmd)


def test_run_scan_adds_inclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scan forwards sonar.inclusions when provided."""
    seen_cmd: list[str] = []

    def _run(cmd, **kwargs):
        seen_cmd.extend(str(item) for item in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    scan_mod.run_scan("token", "main", inclusions="src/foo.py,src/bar.py")
    assert any(arg == "-Dsonar.inclusions=src/foo.py,src/bar.py" for arg in seen_cmd)
