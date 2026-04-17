"""Tests for sonar.api (poll_ce_task, fetch_quality_gate, fetch_project_pull_requests)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

import sonar.api as api_mod


def test_poll_ce_task_success_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_http(url: str, token: str) -> dict:
        return {"task": {"status": "SUCCESS", "analysisId": "a1"}}

    monkeypatch.setattr(api_mod, "_http_get_json", _fake_http)
    result = api_mod.poll_ce_task("http://ce/task", "token", timeout=10, interval=1)
    assert result["status"] == "SUCCESS"
    assert result["analysisId"] == "a1"


def test_poll_ce_task_failed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_http(url: str, token: str) -> dict:
        return {"task": {"status": "FAILED", "errorMessage": "err"}}

    monkeypatch.setattr(api_mod, "_http_get_json", _fake_http)
    with pytest.raises(RuntimeError, match="FAILED"):
        api_mod.poll_ce_task("http://ce/task", "token", timeout=5, interval=1)


def test_poll_ce_task_step_success() -> None:
    def _fake_http(url: str, token: str) -> dict:
        return {"task": {"status": "SUCCESS"}}

    with pytest.MonkeyPatch().context() as m:
        m.setattr(api_mod, "_http_get_json", _fake_http)
        done, task = api_mod._poll_ce_task_step(
            "http://x", "t", time.monotonic() + 60, 60, 1
        )
    assert done is True
    assert task["status"] == "SUCCESS"


def test_poll_ce_task_step_failed_raises() -> None:
    def _fake_http(url: str, token: str) -> dict:
        return {"task": {"status": "CANCELED", "errorMessage": "cancelled"}}

    with pytest.MonkeyPatch().context() as m:
        m.setattr(api_mod, "_http_get_json", _fake_http)
        with pytest.raises(RuntimeError, match="CANCELED"):
            api_mod._poll_ce_task_step(
                "http://x", "t", time.monotonic() + 60, 60, 1
            )


def test_fetch_quality_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_params(base: str, token: str, params: dict) -> dict:
        return {"projectStatus": {"status": "OK"}}

    monkeypatch.setattr(api_mod, "_http_get_json_with_params", _fake_params)
    result = api_mod.fetch_quality_gate(
        "https://sonar/", "token", "proj", "main"
    )
    assert result["projectStatus"]["status"] == "OK"


def test_fetch_quality_gate_with_analysis_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_params(base: str, token: str, params: dict) -> dict:
        assert "analysisId" in params
        return {"projectStatus": {}}

    monkeypatch.setattr(api_mod, "_http_get_json_with_params", _fake_params)
    api_mod.fetch_quality_gate(
        "https://sonar/", "token", "proj", "main", analysis_id="aid1"
    )


def test_fetch_project_pull_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_params(base: str, token: str, params: dict) -> dict:
        return {"pullRequests": [{"key": "1"}]}

    monkeypatch.setattr(api_mod, "_http_get_json_with_params", _fake_params)
    result = api_mod.fetch_project_pull_requests("https://sonar/", "token", "proj")
    assert len(result) == 1
    assert result[0]["key"] == "1"


def test_fetch_project_pull_requests_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_mod, "_http_get_json_with_params", lambda *a, **k: {"pullRequests": "x"}
    )
    result = api_mod.fetch_project_pull_requests("https://sonar/", "token", "proj")
    assert result == []


def test_fetch_new_issues_one_page(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_params(url: str, token: str, params: dict) -> dict:
        return {
            "issues": [
                {"key": "k1", "rule": "r1", "severity": "major", "message": "m1",
                 "component": "proj:src/f.py", "line": 1, "type": "BUG"},
            ],
            "paging": {"total": 1, "pageSize": 500, "pageIndex": 1},
        }

    monkeypatch.setattr(api_mod, "_http_get_json_with_params", _fake_params)
    issues, stats = api_mod.fetch_new_issues(
        "https://sonar/", "token", "proj", "main", page_size=500
    )
    assert len(issues) == 1
    assert issues[0].message == "m1"
    assert stats["new_issues"] == 1
    assert stats["raw_new_issues"] == 1


def test_fetch_pull_request_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_params(url: str, token: str, params: dict) -> dict:
        assert params.get("pullRequest") == "42"
        return {
            "issues": [],
            "paging": {"total": 0, "pageSize": 500, "pageIndex": 1},
        }

    monkeypatch.setattr(api_mod, "_http_get_json_with_params", _fake_params)
    issues, stats = api_mod.fetch_pull_request_issues(
        "https://sonar/", "token", "proj", "42", page_size=500
    )
    assert len(issues) == 0
    assert "pr_issues" in stats
