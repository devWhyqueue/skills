from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import typecheck.gate as pyright_gate


def test_run_pyright_gate_uses_project_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tmp_path / "pyrightconfig.json"
    config.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("PYRIGHT_CONFIG", str(config))

    def _fake_run(cmd: list[str], env: dict | None = None) -> tuple[int, str, str]:
        assert cmd[:2] == ["pyright", "--outputjson"]
        assert cmd[2:4] == ["--project", str(config)]
        return 0, "{\"generalDiagnostics\": []}", ""

    monkeypatch.setattr(pyright_gate, "tool_cmd", lambda _: ["pyright"])
    monkeypatch.setattr(pyright_gate, "run", _fake_run)

    report, summary, failed = pyright_gate.run_pyright_gate(
        enabled=True, package_dir=None
    )

    assert failed is False
    assert summary is None
    assert report is not None
    assert report["config"] is not None
    assert Path(str(report["config"])) == config


def test_run_pyright_gate_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str], env: dict | None = None) -> tuple[int, str, str]:
        payload = {
            "generalDiagnostics": [
                {
                    "file": "x.py",
                    "range": {"start": {"line": 3}},
                    "severity": "error",
                    "rule": "reportSomething",
                    "message": "bad type",
                }
            ]
        }
        return 1, json.dumps(payload), ""

    monkeypatch.setattr(pyright_gate, "tool_cmd", lambda _: ["pyright"])
    monkeypatch.setattr(pyright_gate, "run", _fake_run)

    report, summary, failed = pyright_gate.run_pyright_gate(
        enabled=True, package_dir=None
    )

    assert failed is True
    assert summary == "Pyright type check failed."
    assert report is not None
    assert report["exit_code"] == 1
    assert report["issues"] == [
        {
            "file": "x.py",
            "line": 4,
            "severity": "error",
            "rule": "reportSomething",
            "message": "bad type",
        }
    ]
