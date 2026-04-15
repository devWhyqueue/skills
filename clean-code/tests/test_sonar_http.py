"""Tests for sonar.http (SonarIssue, SonarGateResult, _component_path, _is_exempt_from_sonar_s138)."""
from __future__ import annotations

from typing import Any

import pytest

from sonar.http import (
    SonarGateResult,
    SonarIssue,
    _component_path,
    _is_exempt_from_sonar_s138,
)


def test_sonar_issue_repr() -> None:
    issue = SonarIssue(
        key="k1",
        rule="r1",
        severity="major",
        message="msg",
        component="proj:src/foo.py",
        line=10,
        type="BUG",
    )
    r = repr(issue)
    assert "SonarIssue" in r
    assert "major" in r
    assert "msg" in r


def test_sonar_gate_result_dataclass() -> None:
    r = SonarGateResult(
        status="OK",
        raw_status="OK",
        conditions=[],
        issues=[],
        issues_stats={},
    )
    assert r.status == "OK"
    assert r.conditions == []


def test_component_path_no_colon() -> None:
    assert _component_path("src/foo.py") == "src/foo.py"


def test_component_path_with_colon() -> None:
    assert _component_path("proj:src/foo.py") == "src/foo.py"


def test_is_exempt_from_sonar_s138_dag_decorator() -> None:
    source = """
@dag()
def my_dag():
    pass
"""
    assert _is_exempt_from_sonar_s138(source, 3) is True
    assert _is_exempt_from_sonar_s138(source, 4) is True


def test_is_exempt_from_sonar_s138_task_group() -> None:
    source = """
@task_group()
def my_tg():
    pass
"""
    assert _is_exempt_from_sonar_s138(source, 3) is True


def test_is_exempt_from_sonar_s138_not_decorated() -> None:
    source = """
def normal_func():
    x = 1
"""
    assert _is_exempt_from_sonar_s138(source, 2) is False
    assert _is_exempt_from_sonar_s138(source, 3) is False


def test_is_exempt_from_sonar_s138_syntax_error() -> None:
    assert _is_exempt_from_sonar_s138("def broken(", 1) is False


def test_http_get_json_with_params_adds_cache_buster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_get_json(url: str, token: str) -> dict[str, Any]:
        captured["url"] = url
        captured["token"] = token
        return {"ok": True}

    monkeypatch.setattr("sonar.http._http_get_json", _fake_get_json)

    from sonar.http import _http_get_json_with_params

    result = _http_get_json_with_params(
        "https://sonar.example/api/ce/task", "secret", {"id": "123"}
    )

    assert result == {"ok": True}
    assert captured["token"] == "secret"
    assert "id=123" in captured["url"]
    assert "_ts=" in captured["url"]
