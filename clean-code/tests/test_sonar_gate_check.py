"""Tests for sonar.gate_check (helpers and run_gate_check with mocks)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

import sonar.api as sonar_api
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


def test_sonar_temp_base_dir_defaults_to_tmp_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SONAR_TMPDIR", raising=False)
    if gate_check.os.name == "nt":
        pytest.skip("POSIX-only behavior")
    assert gate_check._sonar_temp_base_dir() == Path("/tmp")


def test_sonar_temp_base_dir_uses_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SONAR_TMPDIR", str(tmp_path))
    assert gate_check._sonar_temp_base_dir() == tmp_path.resolve()


def test_wait_for_analysis_no_ce_task_url() -> None:
    result = gate_check._wait_for_analysis({}, "token")
    assert result is None


def test_wait_for_analysis_with_ce_task(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_poll(url: str, token: str, **kwargs: Any) -> Dict[str, Any]:
        return {"analysisId": "aid123"}

    monkeypatch.setattr(gate_check, "poll_ce_task", _fake_poll)
    result = gate_check._wait_for_analysis({"ceTaskUrl": "http://x"}, "token")
    assert result == "aid123"


def test_append_cache_buster_preserves_existing_query() -> None:
    url = sonar_api._append_cache_buster("https://sonar/api/ce/task?id=123")
    assert "id=123" in url
    assert "_ts=" in url


def test_next_poll_interval_is_fast_initially() -> None:
    assert sonar_api._next_poll_interval(attempt=0, default_interval=5) == 0.25
    assert sonar_api._next_poll_interval(attempt=1, default_interval=5) == 0.5
    assert sonar_api._next_poll_interval(attempt=4, default_interval=5) == 5.0


def test_poll_ce_task_uses_cache_busted_url_and_fast_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def _fake_http_get_json(url: str, token: str) -> dict[str, Any]:
        calls.append(url)
        if len(calls) == 1:
            return {"task": {"status": "IN_PROGRESS"}}
        return {"task": {"status": "SUCCESS", "analysisId": "aid-1"}}

    monkeypatch.setattr(sonar_api, "_http_get_json", _fake_http_get_json)
    monkeypatch.setattr(sonar_api.time, "sleep", lambda secs: sleeps.append(secs))

    task = sonar_api.poll_ce_task("https://sonar/api/ce/task?id=123", "token")

    assert task["analysisId"] == "aid-1"
    assert len(calls) == 2
    assert all("_ts=" in url for url in calls)
    assert all("id=123" in url for url in calls)
    assert sleeps == [0.25]


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
    assert result.issues == []


def test_fetch_gate_result_skips_issue_fetch_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("issue fetch should be skipped when gate is green")

    monkeypatch.setattr(gate_check, "fetch_quality_gate", _fake_fetch_qg)
    monkeypatch.setattr(gate_check, "_collect_new_issues", _boom)

    result = gate_check._fetch_gate_result(
        "http://h", "t", "proj", "main", "new-code", True, None
    )

    assert result.status == "OK"
    assert result.issues == []
    assert result.issues_stats == {}


def test_fetch_gate_result_fetches_issues_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_fetch_qg(
        host: str, token: str, project: str, branch: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "projectStatus": {
                "status": "ERROR",
                "conditions": [
                    {"metricKey": "new_violations", "status": "ERROR"},
                ],
            }
        }

    captured: dict[str, str] = {}

    def _fake_collect(
        host: str,
        token: str,
        project: str,
        pull_request_key: str | None,
        branch: str,
    ) -> tuple[list[Any], dict[str, int]]:
        captured["branch"] = branch
        return [], {"new_issues": 0}

    monkeypatch.setattr(gate_check, "fetch_quality_gate", _fake_fetch_qg)
    monkeypatch.setattr(gate_check, "_collect_new_issues", _fake_collect)

    result = gate_check._fetch_gate_result(
        "http://h", "t", "proj", "main", "new-code", True, None
    )

    assert result.status == "ERROR"
    assert captured["branch"] == "main"
    assert result.issues_stats == {"new_issues": 0}


def test_run_scan_for_gate_always_passes_explicit_coverage_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_scan(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(gate_check, "run_scan", _fake_run_scan)
    monkeypatch.setattr(gate_check, "read_project_properties", lambda: {})
    monkeypatch.setattr(gate_check, "discover_report_task", lambda **_: ({}, None))
    monkeypatch.setenv("SONAR_TMPDIR", str(tmp_path))

    gate_check._run_scan_for_gate(
        "token",
        "main",
        "https://sonar.example",
        "project-key",
        "src",
        "src/foo.py",
    )

    extra_args = captured["extra_args"]
    assert isinstance(extra_args, list)
    assert "-Dsonar.python.coverage.reportPaths=coverage.xml" in extra_args
    assert captured["scanner_working_directory"] is not None
    assert captured["scanner_metadata_path"] is not None
    assert str(captured["scanner_working_directory"]).startswith(str(tmp_path))


def test_run_scan_for_gate_uses_slim_project_workspace_for_file_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    copied: dict[str, str] = {}
    source_file = tmp_path / "src" / "pkg" / "module.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    coverage_file = tmp_path / "coverage.xml"
    coverage_file.write_text("<coverage />\n", encoding="utf-8")

    def _fake_run_scan(**kwargs: Any) -> None:
        captured.update(kwargs)
        project_base_dir = kwargs["project_base_dir"]
        assert isinstance(project_base_dir, Path)
        copied["source"] = (project_base_dir / "src" / "pkg" / "module.py").read_text(
            encoding="utf-8"
        )
        copied["coverage"] = (project_base_dir / "coverage.xml").read_text(
            encoding="utf-8"
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate_check, "run_scan", _fake_run_scan)
    monkeypatch.setattr(gate_check, "read_project_properties", lambda: {})
    monkeypatch.setattr(gate_check, "discover_report_task", lambda **_: ({}, None))
    monkeypatch.setenv("SONAR_TMPDIR", str(tmp_path / "sonar-tmp"))

    gate_check._run_scan_for_gate(
        "token",
        "main",
        "https://sonar.example",
        "project-key",
        "src/pkg/module.py",
        "src/pkg/module.py",
    )

    project_base_dir = captured["project_base_dir"]
    assert isinstance(project_base_dir, Path)
    assert copied["source"] == "VALUE = 1\n"
    assert copied["coverage"] == "<coverage />\n"
    assert captured["sources"] == "src/pkg/module.py"
    assert captured["inclusions"] == "src/pkg/module.py"
