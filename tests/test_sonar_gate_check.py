"""Tests for sonar.gate_check (helpers and run_gate_check with mocks)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

import sonar.gate_check as gate_check


def test_is_new_code_condition_new_prefix() -> None:
    assert gate_check._is_new_code_condition({"metricKey": "new_coverage"}) is True
    assert gate_check._is_new_code_condition({"metricKey": "coverage"}) is False


def test_is_new_code_condition_leak_period() -> None:
    assert gate_check._is_new_code_condition({"onLeakPeriod": True}) is True


def test_is_new_code_condition_period_index() -> None:
    assert gate_check._is_new_code_condition({"periodIndex": 1}) is True


def test_evaluate_gate_status_full() -> None:
    status, conds = gate_check._evaluate_gate_status(
        [{"status": "OK"}, {"status": "ERROR"}], scope="full"
    )
    assert status == "ERROR"
    assert len(conds) == 2


def test_evaluate_gate_status_new_code_only() -> None:
    conditions = [
        {"metricKey": "new_coverage", "status": "OK"},
        {"metricKey": "coverage", "status": "ERROR"},
    ]
    status, conds = gate_check._evaluate_gate_status(conditions, scope="new-code")
    assert status == "OK"
    assert len(conds) == 1
    assert conds[0]["metricKey"] == "new_coverage"


def test_evaluate_gate_status_none() -> None:
    status, conds = gate_check._evaluate_gate_status([], scope="new-code")
    assert status == "NONE"
    assert conds == []


def test_evaluate_gate_status_invalid_scope() -> None:
    with pytest.raises(ValueError, match="Unsupported gate scope"):
        gate_check._evaluate_gate_status([], scope="invalid")


def test_effective_gate_config_from_props(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate_check,
        "read_project_properties",
        lambda: {"sonar.host.url": "https://sonar", "sonar.projectKey": "myproj"},
    )
    h, p, s = gate_check._effective_gate_config(None, None, None)
    assert h == "https://sonar"
    assert p == "myproj"
    assert s == "src"


def test_effective_gate_config_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate_check, "read_project_properties", lambda: {})
    with pytest.raises(RuntimeError, match="Missing Sonar config"):
        gate_check._effective_gate_config(None, None, None)


def test_wait_for_analysis_no_ce_task_url() -> None:
    result = gate_check._wait_for_analysis({}, "token")
    assert result is None


def test_wait_for_analysis_with_ce_task(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_poll(url: str, token: str, **kwargs: Any) -> Dict[str, Any]:
        return {"analysisId": "aid123"}

    monkeypatch.setattr(gate_check, "poll_ce_task", _fake_poll)
    result = gate_check._wait_for_analysis({"ceTaskUrl": "http://x"}, "token")
    assert result == "aid123"


def test_collect_new_issues_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch(
        host: str, token: str, project: str, branch: str, **kwargs: Any
    ) -> tuple[List[Any], Dict[str, int]]:
        return [], {"new_issues": 0}

    monkeypatch.setattr(gate_check, "fetch_new_issues", _fake_fetch)
    issues, stats = gate_check._collect_new_issues(
        "http://h", "t", "proj", None, "main"
    )
    assert issues == []
    assert "new_issues" in stats or stats == {}


def test_fetch_gate_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch_qg(
        host: str, token: str, project: str, branch: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "projectStatus": {
                "status": "OK",
                "conditions": [
                    {"metricKey": "new_coverage", "status": "OK"},
                ],
            }
        }

    monkeypatch.setattr(gate_check, "fetch_quality_gate", _fake_fetch_qg)
    result = gate_check._fetch_gate_result(
        "http://h", "t", "proj", "main", "new-code", False, None
    )
    assert result.status == "OK"
    assert result.raw_status == "OK"
