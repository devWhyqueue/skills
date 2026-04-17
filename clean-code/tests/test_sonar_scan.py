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
    assert any("sonar.scm.disabled=true" in str(c) for c in seen_cmd)
    assert not any("sonar.scm.provider" in str(c) for c in seen_cmd)


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


def test_run_scan_adds_project_base_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_scan forwards sonar.projectBaseDir when provided explicitly."""
    seen_cmd: list[str] = []

    def _run(cmd, **kwargs):
        seen_cmd.extend(str(item) for item in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    scan_mod.run_scan("token", "main", project_base_dir=Path("/tmp/scan-base"))
    assert "--sonar-project-base-dir" in seen_cmd
    assert "/tmp/scan-base" in seen_cmd


def test_run_scan_disables_scanner_qualitygate_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_scan forces pysonar overrides needed by the skill wrapper."""
    captured_env: dict[str, str] = {}

    def _run(cmd, **kwargs):
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})

    scan_mod.run_scan("token", "main")

    assert captured_env["SONAR_QUALITYGATE_WAIT"] == "false"
    assert captured_env["SONAR_SCM_EXCLUSIONS_DISABLED"] == "true"
    assert captured_env["SONAR_SCM_DISABLED"] == "true"
    assert captured_env["SONAR_PYTHON_ANALYSIS_PARALLEL"] == "false"


def test_run_scan_skips_duplicate_inclusions_when_sources_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_cmd: list[str] = []

    def _run(cmd, **kwargs):
        seen_cmd.extend(str(item) for item in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})

    scan_mod.run_scan(
        "token",
        "main",
        sources="src/foo.py,src/bar.py",
        inclusions="src/foo.py,src/bar.py",
    )

    assert not any(arg.startswith("-Dsonar.inclusions=") for arg in seen_cmd)


def test_run_scan_timeout_includes_analysis_log_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Timeouts include the tail of analysis.log for debugging scanner hangs."""
    workdir = tmp_path / ".sonar"
    report_dir = workdir / "scanner-report"
    report_dir.mkdir(parents=True)
    (report_dir / "analysis.log").write_text(
        "line 1\nline 2\nINFO: Preprocessed 0 files\n",
        encoding="utf-8",
    )

    def _run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})

    with pytest.raises(RuntimeError) as exc_info:
        scan_mod.run_scan(
            "token",
            "main",
            scanner_working_directory=workdir,
        )
    message = str(exc_info.value)
    assert "timed out after" in message
    assert "Preprocessed 0 files" in message


def test_run_scan_timeout_ignores_stale_default_analysis_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit workdirs should not fall back to stale .sonar analysis logs."""
    workdir = tmp_path / ".sonar-active"
    workdir.mkdir()
    stale_report_dir = tmp_path / ".sonar" / "scanner-report"
    stale_report_dir.mkdir(parents=True)
    (stale_report_dir / "analysis.log").write_text(
        "stale log\n",
        encoding="utf-8",
    )

    def _run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(scan_mod, "read_project_properties", lambda: {})
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        scan_mod.run_scan(
            "token",
            "main",
            scanner_working_directory=workdir,
        )

    assert "stale log" not in str(exc_info.value)


def test_scan_timeout_uses_updated_default_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SONAR_SCAN_TIMEOUT_SEC", raising=False)
    assert scan_mod._scan_timeout_seconds() == 1200
