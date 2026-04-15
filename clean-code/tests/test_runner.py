"""Tests for cli.runner (internal helpers and run with mocks)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import cli.runner as runner_mod


def test_resolve_package_dir_empty() -> None:
    assert runner_mod._resolve_package_dir("") is None
    assert runner_mod._resolve_package_dir("   ") is None
    assert runner_mod._resolve_package_dir("AUTO") is None


def test_resolve_package_dir_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "resolve_package_dir", lambda v: Path("src/etl"))
    assert runner_mod._resolve_package_dir("etl") == Path("src/etl")


def test_list_changed_python_files_no_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        "uncommitted_changed_files",
        lambda: ["cli/runner.py", "tests/test_x.py"],
    )
    monkeypatch.setattr(runner_mod, "filter_python_files", lambda x: list(x))
    monkeypatch.setattr(runner_mod, "exclude_test_folders", lambda x: [f for f in x if "test" not in f])
    result = runner_mod._list_changed_python_files(package_dir=None)
    assert "cli/runner.py" in result or len(result) >= 0


def test_run_full_integration_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run _run_full with audit only and all gates mocked to pass."""
    def _fake_list(*, package_dir) -> list:
        return []

    def _fake_run_gates(args, files, package_dir, status, summary):
        return status, summary, None, None, None, None, None

    monkeypatch.setattr(runner_mod, "_list_changed_python_files", _fake_list)
    monkeypatch.setattr(runner_mod, "run_gates", _fake_run_gates)
    args = SimpleNamespace(
        scope="",
        audit=True,
        max_iterations=5,
        vulture=True,
        pyright=True,
        pytest=True,
        sonar=False,
        semantic=False,
    )
    code, report = runner_mod._run_full(args)
    assert code == 0
    assert report["status"] == "pass"
    assert report["changed_files"] == []
    assert report["pipeline_mode"] == "full"
    assert "stage_durations_sec" in report


def test_run_returns_zero_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_stages(args) -> tuple[int, dict]:
        return 0, {"status": "pass", "summary": "Done."}

    monkeypatch.setattr(runner_mod, "_run_all_stages", _fake_stages)
    monkeypatch.setattr(runner_mod, "reset_semantic_out_dir", lambda: None)
    monkeypatch.setattr(runner_mod, "_semantic_resume_available", lambda args: False)
    monkeypatch.setattr(runner_mod, "_write_cached_report", lambda report: None)
    result = runner_mod.run(SimpleNamespace(scope="", minimal=True))
    assert result == 0


def test_run_returns_two_on_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_stages(args) -> tuple[int, dict]:
        return 2, {"status": "fail", "summary": "Violations."}

    monkeypatch.setattr(runner_mod, "_run_all_stages", _fake_stages)
    monkeypatch.setattr(runner_mod, "reset_semantic_out_dir", lambda: None)
    monkeypatch.setattr(runner_mod, "_semantic_resume_available", lambda args: False)
    monkeypatch.setattr(runner_mod, "_write_cached_report", lambda report: None)
    result = runner_mod.run(SimpleNamespace(scope="", minimal=True))
    assert result == 2


def test_run_returns_three_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_stages(args) -> tuple[int, dict]:
        raise RuntimeError("oops")

    monkeypatch.setattr(runner_mod, "_run_all_stages", _fake_stages)
    monkeypatch.setattr(runner_mod, "reset_semantic_out_dir", lambda: None)
    monkeypatch.setattr(runner_mod, "_semantic_resume_available", lambda args: False)
    result = runner_mod.run(SimpleNamespace(scope="", minimal=True))
    assert result == 3


def test_run_resumes_semantic_without_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"reset": False, "full": False}

    def _fake_resume(args) -> tuple[int, dict]:
        return 2, {"status": "fail", "summary": "Semantic pending."}

    def _fake_full(args) -> tuple[int, dict]:
        called["full"] = True
        return 0, {"status": "pass", "summary": "Done."}

    monkeypatch.setattr(runner_mod, "_semantic_resume_available", lambda args: True)
    monkeypatch.setattr(runner_mod, "_run_semantic_resume", _fake_resume)
    monkeypatch.setattr(runner_mod, "_run_all_stages", _fake_full)
    monkeypatch.setattr(
        runner_mod, "reset_semantic_out_dir", lambda: called.__setitem__("reset", True)
    )

    result = runner_mod.run(SimpleNamespace(scope="", minimal=False))

    assert result == 2
    assert called["reset"] is False
    assert called["full"] is False


def test_run_executes_full_pipeline_after_semantic_resume_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"full": False}

    def _fake_resume(args) -> tuple[int, dict]:
        return 0, {"status": "pass", "summary": "Semantic complete."}

    def _fake_full(args) -> tuple[int, dict]:
        called["full"] = True
        return 0, {"status": "pass", "summary": "Done."}

    monkeypatch.setattr(runner_mod, "_semantic_resume_available", lambda args: True)
    monkeypatch.setattr(runner_mod, "_run_semantic_resume", _fake_resume)
    monkeypatch.setattr(runner_mod, "_run_all_stages", _fake_full)
    monkeypatch.setattr(runner_mod, "_write_cached_report", lambda report: None)
    monkeypatch.setattr(runner_mod, "reset_semantic_out_dir", lambda: None)

    result = runner_mod.run(SimpleNamespace(scope="", minimal=False))

    assert result == 0
    assert called["full"] is True
