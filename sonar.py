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

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


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
    candidates = [
        Path(".sonar/report-task.txt"),  # SonarScanner's default working directory in many setups
        Path(".scannerwork/report-task.txt"),  # legacy/default for other scanners
    ]

    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise RuntimeError("Missing report-task.txt (pysonar output).")

    data: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def _read_sonar_project_properties(path: Path = Path("sonar-project.properties")) -> Dict[str, str]:
    """
    Parse `sonar-project.properties` into a simple dict.

    This intentionally supports only basic `key=value` lines.
    """
    if not path.exists():
        return {}

    props: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if not key:
            continue
        props[key] = v.strip()
    return props


def run_pysonar(
    token: str,
    branch: str,
    host_url: Optional[str] = None,
    project_key: Optional[str] = None,
    sources: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> None:
    extra_args = extra_args or []

    # Ensure `sitecustomize.py` in this skill directory is importable by the
    # `pysonar` subprocess so we can inject system CA certificates via truststore.
    env = os.environ.copy()
    skill_dir = str(Path(__file__).resolve().parent)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = skill_dir if not existing_pythonpath else f"{skill_dir}{os.pathsep}{existing_pythonpath}"

    # Avoid reading stale task metadata from a previous run.
    for stale in (Path(".sonar/report-task.txt"), Path(".scannerwork/report-task.txt")):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    props = _read_sonar_project_properties()

    cmd = _venv_tool_cmd("pysonar") + ["-t", token, "--sonar-branch-name", branch]

    if host_url:
        cmd.extend(["--sonar-host-url", host_url])
    if project_key:
        cmd.extend(["--sonar-project-key", project_key])
    if sources:
        cmd.extend(["--sonar-sources", sources])

    if "sonar.sourceEncoding" not in props:
        cmd.append("-Dsonar.sourceEncoding=UTF-8")
    if "sonar.scm.provider" not in props:
        cmd.append("-Dsonar.scm.provider=git")
    if "sonar.exclusions" not in props:
        cmd.append(
            "-Dsonar.exclusions=**/.venv/**,**/venv/**,**/.mypy_cache/**,**/.ruff_cache/**,**/__pycache__/**,**/dist/**,**/build/**,**/.git/**"
        )

    cmd += extra_args

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    code, out, err = p.returncode, p.stdout, p.stderr
    if code != 0:
        # Some configurations exit non-zero for a failed Quality Gate, while still
        # producing `report-task.txt`. We want gate-only enforcement via API.
        try:
            _read_report_task()
        except Exception as e:
            raise RuntimeError(f"pysonar failed (exit {code}).\nSTDOUT:\n{out}\nSTDERR:\n{err}") from e


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
    token: str,
    branch: str,
    host_url: Optional[str] = None,
    project_key: Optional[str] = None,
    sources: Optional[str] = None,
) -> SonarGateResult:
    """
    Gate-only mode:
    - run pysonar
    - wait for CE task
    - fetch quality gate
    - do NOT fetch issues (you asked for gate-only)
    """

    extra_args = [
        # Let the skill enforce the gate via API to keep pysonar exit codes stable.
        "--no-sonar-qualitygate-wait",
        # Avoid warnings when `requires-python` contains specifiers like "~=3.12.0".
        f"-Dsonar.python.version={sys.version_info.major}.{sys.version_info.minor}",
        # Airflow DAGs are often intentionally long; ignore the "too many lines" rule in dags/**.
        "-Dsonar.issue.ignore.multicriteria=e1",
        "-Dsonar.issue.ignore.multicriteria.e1.ruleKey=python:S138",
        "-Dsonar.issue.ignore.multicriteria.e1.resourceKey=**/dags/**",
    ]
    props = _read_sonar_project_properties()
    effective_host_url = host_url or props.get("sonar.host.url")
    effective_project_key = project_key or props.get("sonar.projectKey")
    effective_sources = sources or props.get("sonar.sources") or "src"

    if not effective_host_url or not effective_project_key:
        raise RuntimeError(
            "Missing Sonar config. Provide `sonar-project.properties` with "
            "`sonar.host.url` and `sonar.projectKey`, or pass --sonar-host-url / --sonar-project-key."
        )

    run_pysonar(
        token=token,
        branch=branch,
        host_url=effective_host_url,
        project_key=effective_project_key,
        sources=effective_sources,
        extra_args=extra_args,
    )

    report = _read_report_task()
    ce_task_url = report.get("ceTaskUrl")
    if not ce_task_url:
        raise RuntimeError("report-task.txt missing ceTaskUrl")

    analysis_id = wait_for_compute_engine(ce_task_url, token)

    server_url = report.get("serverUrl") or effective_host_url
    report_project_key = report.get("projectKey") or effective_project_key
    gate = fetch_quality_gate(server_url, token, report_project_key, branch, analysis_id=analysis_id)
    project_status = gate.get("projectStatus", {})
    status = project_status.get("status", "NONE")
    conditions = project_status.get("conditions", [])

    return SonarGateResult(status=status, conditions=conditions, issues=[])
