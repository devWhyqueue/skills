from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sonar.gate as sonar_gate


def test_run_sonar_gate_returns_failure_on_scanner_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SONAR_TOKEN", "token")
    monkeypatch.setenv("SONAR_HOST_URL", "https://sonar.example")
    monkeypatch.setenv("SONAR_PROJECT_KEY", "project-key")

    def _boom(**_: Any) -> Any:
        raise RuntimeError("Missing report-task.txt (pysonar output).")

    monkeypatch.setattr(sonar_gate, "run_gate_check", _boom)

    with pytest.raises(RuntimeError, match="Missing report-task\\.txt"):
        sonar_gate.run_sonar_gate(enabled=True, package_dir=None)
