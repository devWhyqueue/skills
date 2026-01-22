#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SonarIssue:
    key: str
    rule: str
    severity: str
    message: str
    component: str
    line: Optional[int]
    type: str


@dataclass
class SonarGateResult:
    status: str  # OK | ERROR | NONE
    conditions: List[Dict[str, Any]]
    issues: List[SonarIssue]


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr


def _venv_tool_cmd(tool: str) -> List[str]:
    """
    Resolve a console script from this skill's `.venv`.

    This skill is meant to be run with `...\\.venv\\Scripts\\python.exe` without
    relying on PATH or external fallbacks.
    """
    exe_suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).with_name(f"{tool}{exe_suffix}")
    if sibling.exists():
        return [str(sibling)]

    raise RuntimeError(
        f"Missing required tool '{tool}{exe_suffix}' next to interpreter: {Path(sys.executable)}"
    )


def _basic_auth_header(token: str) -> str:
    raw = f"{token}:".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _http_get_json(url: str, token: str) -> Dict[str, Any]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _basic_auth_header(token))
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_report_task() -> Dict[str, str]:
    path = Path(".scannerwork/report-task.txt")
    if not path.exists():
        raise RuntimeError("Missing .scannerwork/report-task.txt (pysonar output).")

    data: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def run_pysonar(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    sources: str = "src",
    extra_args: Optional[List[str]] = None,
) -> None:
    extra_args = extra_args or []

    cmd = _venv_tool_cmd("pysonar") + [
        f"-Dsonar.host.url={host_url}",
        f"-Dsonar.token={token}",
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.branch.name={branch}",
        f"-Dsonar.sources={sources}",
        "-Dsonar.sourceEncoding=UTF-8",
        "-Dsonar.scm.provider=git",
        "-Dsonar.exclusions=**/.venv/**,**/venv/**,**/.mypy_cache/**,**/.ruff_cache/**,**/__pycache__/**,**/dist/**,**/build/**,**/.git/**",
    ] + extra_args

    code, out, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"pysonar failed (exit {code}).\nSTDOUT:\n{out}\nSTDERR:\n{err}")


def wait_for_compute_engine(task_url: str, token: str, timeout_seconds: int = 180) -> str:
    deadline = time.time() + timeout_seconds
    last_status = None

    while time.time() < deadline:
        payload = _http_get_json(task_url, token)
        task = payload.get("task", {})
        last_status = task.get("status")

        if last_status == "SUCCESS":
            analysis_id = task.get("analysisId")
            if not analysis_id:
                raise RuntimeError("Compute Engine SUCCESS but analysisId missing.")
            return analysis_id

        if last_status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Compute Engine task ended with status={last_status}")

        time.sleep(2)

    raise RuntimeError(f"Timed out waiting for CE task. Last status={last_status}")


def fetch_quality_gate(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    analysis_id: Optional[str] = None,
) -> Dict[str, Any]:
    base = host_url.rstrip("/")
    params = {"projectKey": project_key, "branch": branch}
    if analysis_id:
        params = {"analysisId": analysis_id}

    url = f"{base}/api/qualitygates/project_status?{urllib.parse.urlencode(params)}"
    return _http_get_json(url, token)


def run_sonar_gate_check(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    sources: str = "src",
) -> SonarGateResult:
    """
    Gate-only mode:
    - run pysonar
    - wait for CE task
    - fetch quality gate
    - do NOT fetch issues (you asked for gate-only)
    """

    extra_args = [
        # Airflow DAGs are often intentionally long; ignore the "too many lines" rule in dags/**.
        "-Dsonar.issue.ignore.multicriteria=e1",
        "-Dsonar.issue.ignore.multicriteria.e1.ruleKey=python:S138",
        "-Dsonar.issue.ignore.multicriteria.e1.resourceKey=**/dags/**",
    ]
    run_pysonar(host_url, token, project_key, branch, sources=sources, extra_args=extra_args)

    report = _read_report_task()
    ce_task_url = report.get("ceTaskUrl")
    if not ce_task_url:
        raise RuntimeError("report-task.txt missing ceTaskUrl")

    analysis_id = wait_for_compute_engine(ce_task_url, token)

    gate = fetch_quality_gate(host_url, token, project_key, branch, analysis_id=analysis_id)
    project_status = gate.get("projectStatus", {})
    status = project_status.get("status", "NONE")
    conditions = project_status.get("conditions", [])

    return SonarGateResult(status=status, conditions=conditions, issues=[])
