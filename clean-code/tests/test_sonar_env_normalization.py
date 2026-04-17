from __future__ import annotations

from typing import Any

import pytest

import sonar.gate as sonar_gate


def test_run_sonar_gate_strips_embedded_property_prefix_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONAR_TOKEN", "token")
    monkeypatch.setenv("SONAR_HOST_URL", "sonar.host.url=https://sonar.example/sonar")
    monkeypatch.setenv("SONAR_PROJECT_KEY", "sonar.projectKey=project-key")

    def _fake_run_gate_check(**kwargs: Any) -> Any:
        assert kwargs["host_url"] == "https://sonar.example/sonar"
        assert kwargs["project_key"] == "project-key"

        class _Gate:
            status = "OK"
            raw_status = "OK"
            conditions: list[dict[str, Any]] = []
            issues: list[Any] = []
            issues_stats: dict[str, int] = {}

        return _Gate()

    monkeypatch.setattr(sonar_gate, "run_gate_check", _fake_run_gate_check)

    report, summary, failed = sonar_gate.run_sonar_gate(enabled=True, package_dir=None)
    assert failed is False
    assert summary is None
    assert report is not None
