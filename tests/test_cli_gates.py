"""Tests for cli.gates."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

import cli.gates as gates_mod


def test_run_gates_vulture_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_vulture(*, enabled: bool, changed_files: list) -> tuple[Optional[Any], Optional[str], bool]:
        return {"tool": "vulture"}, "Vulture failed.", True

    def _fake_pyright(*, enabled: bool, changed_files: list) -> tuple[None, None, False]:
        return None, None, False

    def _fake_pytest(*, enabled: bool, changed_files: list, package_dir: Optional[Path], **kwargs: Any) -> tuple[None, None, bool]:
        return None, None, False

    monkeypatch.setattr(gates_mod, "run_vulture_gate", _fake_vulture)
    monkeypatch.setattr(gates_mod, "run_pyright_gate", _fake_pyright)
    monkeypatch.setattr(gates_mod, "run_pytest_gate", _fake_pytest)
    monkeypatch.setattr(gates_mod, "run_sonar_gate", lambda *a, **k: (None, None, False))
    monkeypatch.setattr(gates_mod, "run_semantic_gate_if_enabled", lambda *a, **k: None)

    args = SimpleNamespace(vulture=True, pyright=True, pytest=True, sonar=False, semantic=False)
    status, summary, v, pr, py, so, se = gates_mod.run_gates(
        args, ["x.py"], None, "pass", "ok"
    )
    assert status == "fail"
    assert "Vulture" in (summary or "")
    assert v is not None


def test_run_gates_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_vulture(*, enabled: bool, changed_files: list) -> tuple[dict, None, bool]:
        return {"tool": "vulture"}, None, False

    def _fake_pyright(*, enabled: bool, changed_files: list) -> tuple[dict, None, bool]:
        return {"tool": "pyright"}, None, False

    def _fake_pytest(*, enabled: bool, changed_files: list, package_dir: Any, **kwargs: Any) -> tuple[dict, None, bool]:
        return {"tool": "pytest"}, None, False

    monkeypatch.setattr(gates_mod, "run_vulture_gate", _fake_vulture)
    monkeypatch.setattr(gates_mod, "run_pyright_gate", _fake_pyright)
    monkeypatch.setattr(gates_mod, "run_pytest_gate", _fake_pytest)
    monkeypatch.setattr(gates_mod, "run_sonar_gate", lambda *a, **k: (None, None, False))
    monkeypatch.setattr(gates_mod, "run_semantic_gate_if_enabled", lambda *a, **k: None)

    args = SimpleNamespace(vulture=True, pyright=True, pytest=True, sonar=False, semantic=False)
    status, summary, v, pr, py, so, se = gates_mod.run_gates(
        args, ["x.py"], None, "pass", "ok"
    )
    assert status == "pass"
    assert v is not None
    assert pr is not None
    assert py is not None


def test_run_gates_semantic_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_vulture(*_, **__) -> tuple[dict, None, bool]:
        return {"tool": "vulture"}, None, False

    def _fake_pyright(*_, **__) -> tuple[dict, None, bool]:
        return {"tool": "pyright"}, None, False

    def _fake_pytest(*_, **__) -> tuple[dict, None, bool]:
        return {"tool": "pytest"}, None, False

    def _fake_semantic(*_, **__) -> dict:
        return {"status": "fail", "summary": {"fails": 1}, "ledger_path": "/x"}

    monkeypatch.setattr(gates_mod, "run_vulture_gate", _fake_vulture)
    monkeypatch.setattr(gates_mod, "run_pyright_gate", _fake_pyright)
    monkeypatch.setattr(gates_mod, "run_pytest_gate", _fake_pytest)
    monkeypatch.setattr(gates_mod, "run_sonar_gate", lambda *a, **k: (None, None, False))
    monkeypatch.setattr(gates_mod, "run_semantic_gate_if_enabled", _fake_semantic)

    args = SimpleNamespace(vulture=True, pyright=True, pytest=True, sonar=False, semantic=True)
    status, summary, *_ = gates_mod.run_gates(args, ["x.py"], None, "pass", "ok")
    assert status == "fail"
    assert summary is not None
