from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sonar.gate as sonar_gate
import sonar.props as sonar_props


def test_run_sonar_gate_strips_embedded_property_prefix_from_props(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SONAR_TOKEN", "token")

    (tmp_path / "sonar-project.properties").write_text(
        "sonar.host.url=sonar.host.url=https://sonar.example/sonar\n"
        "sonar.projectKey=sonar.projectKey=project-key\n",
        encoding="utf-8",
    )

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


def test_changed_files_prefer_exact_sources_over_broad_parent_dirs() -> None:
    host, project, sources = sonar_props._env_host_project_sources(
        package_dir=None,
        props={},
        changed_files=[
            "src/foo/__init__.py",
            "src/foo/a.py",
            "src/foo/nested/b.py",
            "src/top_level.py",
        ],
    )

    assert host == ""
    assert project == ""
    assert sources == "src/foo/a.py,src/foo/nested/b.py,src/top_level.py"
