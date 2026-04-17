"""Tests for sonar.gate (run_sonar_gate, build_sonar_report_dict)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from sonar.http import SonarGateResult, SonarIssue
import sonar.gate as gate_mod


def test_build_sonar_report_dict() -> None:
    gate = SonarGateResult(
        status="OK",
        raw_status="OK",
        conditions=[{"metricKey": "new_coverage", "status": "OK"}],
        issues=[],
        issues_stats={},
    )
    report = gate_mod.build_sonar_report_dict(
        gate, "main", "proj", "src", "develop", "new-code"
    )
    assert report["quality_gate"] == "OK"
    assert report["project_key"] == "proj"
    assert report["branch"] == "main"
    assert report["new_issues"] == []
    assert report["sources"] == "src"


def test_build_sonar_report_dict_with_issues() -> None:
    issue = SonarIssue(
        key="k", rule="r", severity="major", message="m",
        component="c", line=1, type="BUG",
    )
    gate = SonarGateResult(
        status="ERROR",
        raw_status="ERROR",
        conditions=[],
        issues=[issue],
        issues_stats={"new_issues": 1},
    )
    report = gate_mod.build_sonar_report_dict(
        gate, "main", "proj", "src", "develop", "new-code"
    )
    new_issues = cast(list[dict[str, Any]], report["new_issues"])
    assert report["quality_gate"] == "ERROR"
    assert len(new_issues) == 1
    assert new_issues[0]["message"] == "m"


def test_run_sonar_gate_disabled() -> None:
    report, summary, failed = gate_mod.run_sonar_gate(
        enabled=False, package_dir=None, changed_files=[]
    )
    assert report is None
    assert summary is None
    assert failed is False


def test_run_sonar_gate_misconfigured_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate_mod, "resolve_sonar_env", lambda *a, **k: (None, None, None, "", "main"))
    report, summary, failed = gate_mod.run_sonar_gate(
        enabled=True, package_dir=None, changed_files=["x.py"]
    )
    assert failed is True
    assert "SONAR_TOKEN" in (summary or "")


def test_sonar_gate_result_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_artifact(
        host: str,
        project: str,
        sources: str,
        inclusions: str | None,
        token: str,
        branch: str,
    ):
        return SonarGateResult("OK", "OK", [], [], {})

    monkeypatch.setattr(gate_mod, "resolve_sonar_env", lambda *a, **k: ("http://s", "p", "src", "t", "main"))
    monkeypatch.setattr(gate_mod, "sonar_gate_misconfigured", lambda *a: None)
    monkeypatch.setattr(gate_mod, "_run_gate_with_artifacts", _fake_artifact)
    from sonar.http import SonarGateResult
    monkeypatch.setattr(gate_mod, "SonarGateResult", SonarGateResult)
    report, summary, failed = gate_mod.run_sonar_gate(
        enabled=True, package_dir=None, changed_files=["x.py"]
    )
    assert failed is False
    assert report is not None


def test_run_sonar_gate_passes_changed_file_inclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str | None] = {}

    def _fake_artifact(
        host: str,
        project: str,
        sources: str,
        inclusions: str | None,
        token: str,
        branch: str,
    ) -> SonarGateResult:
        captured["sources"] = sources
        captured["inclusions"] = inclusions
        return SonarGateResult("OK", "OK", [], [], {})

    monkeypatch.setattr(
        gate_mod,
        "resolve_sonar_env",
        lambda *a, **k: (
            "http://s",
            "p",
            "src/bar/c.py,src/foo/a.py,src/foo/b.py",
            "t",
            "main",
        ),
    )
    monkeypatch.setattr(gate_mod, "sonar_gate_misconfigured", lambda *a: None)
    monkeypatch.setattr(gate_mod, "_run_gate_with_artifacts", _fake_artifact)

    report, summary, failed = gate_mod.run_sonar_gate(
        enabled=True,
        package_dir=None,
        changed_files=[
            "src/foo/__init__.py",
            "src/foo/a.py",
            "src/foo/b.py",
            "src/bar/c.py",
        ],
    )

    assert failed is False
    assert summary is None
    assert report is not None
    assert captured["sources"] == "src/bar/c.py,src/foo/a.py,src/foo/b.py"
    assert captured["inclusions"] == "src/bar/c.py,src/foo/a.py,src/foo/b.py"
