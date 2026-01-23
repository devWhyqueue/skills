#!/usr/bin/env python3
from __future__ import annotations

import base64
import ast
import json
import os
import subprocess
import sys
import tempfile
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
    status: str  # OK | ERROR | NONE (evaluated, may be scoped)
    raw_status: str  # OK | ERROR | NONE (server-reported)
    conditions: List[Dict[str, Any]]
    issues: List[SonarIssue]
    issues_stats: Dict[str, int]


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


def _http_get_json_with_params(
    base_url: str, token: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return _http_get_json(url, token)


def _read_report_task(report_task_path: Optional[Path] = None) -> Dict[str, str]:
    if report_task_path is not None:
        if not report_task_path.exists():
            raise RuntimeError(
                f"Missing report-task.txt (pysonar output): {report_task_path}"
            )
        path = report_task_path
    else:
        candidates = [
            Path(
                ".sonar/report-task.txt"
            ),  # SonarScanner's default working directory in many setups
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


def _read_sonar_project_properties(
    path: Path = Path("sonar-project.properties"),
) -> Dict[str, str]:
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
    reference_branch: Optional[str] = None,
    scanner_metadata_path: Optional[Path] = None,
    scanner_working_directory: Optional[Path] = None,
    pull_request_key: Optional[str] = None,
    pull_request_branch: Optional[str] = None,
    pull_request_base: Optional[str] = None,
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
    env["PYTHONPATH"] = (
        skill_dir
        if not existing_pythonpath
        else f"{skill_dir}{os.pathsep}{existing_pythonpath}"
    )

    props = _read_sonar_project_properties()

    cmd = _venv_tool_cmd("pysonar") + ["-t", token]
    if pull_request_key:
        cmd.append(f"-Dsonar.pullrequest.key={pull_request_key}")
        cmd.append(f"-Dsonar.pullrequest.branch={pull_request_branch or branch}")
        cmd.append(
            f"-Dsonar.pullrequest.base={pull_request_base or reference_branch or 'develop'}"
        )
    else:
        cmd += ["--sonar-branch-name", branch]

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

    if reference_branch and "sonar.newCode.referenceBranch" not in props:
        cmd.append(f"-Dsonar.newCode.referenceBranch={reference_branch}")

    if scanner_working_directory and "sonar.working.directory" not in props:
        cmd.append(f"-Dsonar.working.directory={scanner_working_directory}")

    if scanner_metadata_path and "sonar.scanner.metadataFilePath" not in props:
        cmd.append(f"-Dsonar.scanner.metadataFilePath={scanner_metadata_path}")

    cmd += extra_args

    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    code, out, err = p.returncode, p.stdout, p.stderr
    if code != 0:
        # Some configurations exit non-zero for a failed Quality Gate, while still
        # producing `report-task.txt`. We want gate-only enforcement via API.
        try:
            _read_report_task(scanner_metadata_path)
        except Exception as e:
            raise RuntimeError(
                f"pysonar failed (exit {code}).\nSTDOUT:\n{out}\nSTDERR:\n{err}"
            ) from e


def wait_for_compute_engine(
    task_url: str, token: str, timeout_seconds: int = 180
) -> str:
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

    return _http_get_json_with_params(
        f"{base}/api/qualitygates/project_status", token, params
    )


def fetch_project_pull_requests(
    host_url: str, token: str, project_key: str
) -> List[Dict[str, Any]]:
    base = host_url.rstrip("/")
    payload = _http_get_json_with_params(
        f"{base}/api/project_pull_requests/list", token, {"project": project_key}
    )
    prs = payload.get("pullRequests", [])
    if not isinstance(prs, list):
        return []
    return prs


def _component_path(component: str) -> str:
    if ":" in component:
        return component.split(":", 1)[1]
    return component


def _is_airflow_dag_or_task_group_decorator(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in {"dag", "task_group"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"dag", "task_group"}
    if isinstance(node, ast.Call):
        return _is_airflow_dag_or_task_group_decorator(node.func)
    return False


def _is_exempt_from_sonar_s138(source: str, line: int) -> bool:
    """
    Return True if `line` belongs to a function decorated with @dag or @task_group.

    This is used ONLY to filter Sonar's python:S138 (function length) issues.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None:
            continue

        if not (start <= line <= end):
            continue

        for dec in node.decorator_list:
            if _is_airflow_dag_or_task_group_decorator(dec):
                return True

    return False


def fetch_new_issues(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    *,
    page_size: int = 500,
) -> tuple[List[SonarIssue], Dict[str, int]]:
    base = host_url.rstrip("/")
    issues: List[SonarIssue] = []
    page = 1
    raw_count = 0
    excluded_s138_decorated = 0
    source_cache: Dict[str, str] = {}

    while True:
        payload = _http_get_json_with_params(
            f"{base}/api/issues/search",
            token,
            {
                "componentKeys": project_key,
                "branch": branch,
                "resolved": "false",
                "sinceLeakPeriod": "true",
                "p": page,
                "ps": page_size,
            },
        )

        raw_issues = payload.get("issues", [])
        for raw in raw_issues:
            raw_count += 1
            issue = SonarIssue(
                key=str(raw.get("key", "")),
                rule=str(raw.get("rule", "")),
                severity=str(raw.get("severity", "")),
                message=str(raw.get("message", "")),
                component=str(raw.get("component", "")),
                line=raw.get("line"),
                type=str(raw.get("type", "")),
            )

            if issue.rule == "python:S138" and issue.line:
                rel_path = _component_path(issue.component)
                try:
                    source = source_cache.get(rel_path)
                    if source is None:
                        source = Path(rel_path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                        source_cache[rel_path] = source
                    if _is_exempt_from_sonar_s138(source, int(issue.line)):
                        excluded_s138_decorated += 1
                        continue
                except Exception:
                    # If we can't inspect the file, do not hide issues.
                    pass

            issues.append(
                SonarIssue(
                    key=issue.key,
                    rule=issue.rule,
                    severity=issue.severity,
                    message=issue.message,
                    component=issue.component,
                    line=issue.line,
                    type=issue.type,
                )
            )

        paging = payload.get("paging", {}) or {}
        total = int(paging.get("total", 0) or 0)
        ps = int(paging.get("pageSize", page_size) or page_size)
        current = int(paging.get("pageIndex", page) or page)
        fetched_so_far = current * ps
        if not raw_issues or fetched_so_far >= total:
            break

        page += 1

    return issues, {
        "raw_new_issues": raw_count,
        "new_issues": len(issues),
        "excluded_s138_decorated": excluded_s138_decorated,
    }


def fetch_pull_request_issues(
    host_url: str,
    token: str,
    project_key: str,
    pull_request_key: str,
    *,
    page_size: int = 500,
) -> tuple[List[SonarIssue], Dict[str, int]]:
    base = host_url.rstrip("/")
    issues: List[SonarIssue] = []
    page = 1
    raw_count = 0
    excluded_s138_decorated = 0
    source_cache: Dict[str, str] = {}

    while True:
        payload = _http_get_json_with_params(
            f"{base}/api/issues/search",
            token,
            {
                "componentKeys": project_key,
                "pullRequest": pull_request_key,
                "resolved": "false",
                "p": page,
                "ps": page_size,
            },
        )

        raw_issues = payload.get("issues", [])
        for raw in raw_issues:
            raw_count += 1
            issue = SonarIssue(
                key=str(raw.get("key", "")),
                rule=str(raw.get("rule", "")),
                severity=str(raw.get("severity", "")),
                message=str(raw.get("message", "")),
                component=str(raw.get("component", "")),
                line=raw.get("line"),
                type=str(raw.get("type", "")),
            )

            if issue.rule == "python:S138" and issue.line:
                rel_path = _component_path(issue.component)
                try:
                    source = source_cache.get(rel_path)
                    if source is None:
                        source = Path(rel_path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                        source_cache[rel_path] = source
                    if _is_exempt_from_sonar_s138(source, int(issue.line)):
                        excluded_s138_decorated += 1
                        continue
                except Exception:
                    pass

            issues.append(issue)

        paging = payload.get("paging", {}) or {}
        total = int(paging.get("total", 0) or 0)
        ps = int(paging.get("pageSize", page_size) or page_size)
        current = int(paging.get("pageIndex", page) or page)
        fetched_so_far = current * ps
        if not raw_issues or fetched_so_far >= total:
            break
        page += 1

    return issues, {
        "raw_pr_issues": raw_count,
        "pr_issues": len(issues),
        "excluded_s138_decorated": excluded_s138_decorated,
    }


def _is_new_code_condition(cond: Dict[str, Any]) -> bool:
    metric_key = str(cond.get("metricKey", "") or "")
    if metric_key.startswith("new_"):
        return True
    if cond.get("onLeakPeriod") is True:
        return True
    if cond.get("periodIndex") is not None:
        return True
    return False


def _evaluate_gate_status(
    conditions: List[Dict[str, Any]], *, scope: str
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Evaluate a quality gate from conditions.

    scope:
    - "full": include all conditions
    - "new-code": include only "new code" / leak-period conditions (PR-scoped)
    """
    if scope not in {"full", "new-code"}:
        raise ValueError(f"Unsupported gate scope: {scope}")

    relevant = (
        conditions
        if scope == "full"
        else [c for c in conditions if _is_new_code_condition(c)]
    )

    if not relevant:
        return "NONE", []

    failing = [c for c in relevant if c.get("status") == "ERROR"]
    return ("ERROR" if failing else "OK"), relevant


def run_sonar_gate_check(
    token: str,
    branch: str,
    reference_branch: Optional[str] = None,
    gate_scope: str = "new-code",
    fetch_new_code_issues: bool = True,
    pull_request_key: Optional[str] = None,
    pull_request_branch: Optional[str] = None,
    pull_request_base: Optional[str] = None,
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

    with tempfile.TemporaryDirectory(prefix="clean-code-pr-review-sonar-") as temp_dir:
        temp_path = Path(temp_dir)
        scanner_working_directory = temp_path / ".scannerwork"
        scanner_metadata_path = temp_path / "report-task.txt"

        run_pysonar(
            token=token,
            branch=branch,
            reference_branch=reference_branch,
            scanner_metadata_path=scanner_metadata_path,
            scanner_working_directory=scanner_working_directory,
            pull_request_key=pull_request_key,
            pull_request_branch=pull_request_branch,
            pull_request_base=pull_request_base,
            host_url=effective_host_url,
            project_key=effective_project_key,
            sources=effective_sources,
            extra_args=extra_args,
        )

        report = _read_report_task(scanner_metadata_path)
        ce_task_url = report.get("ceTaskUrl")
        if not ce_task_url:
            raise RuntimeError("report-task.txt missing ceTaskUrl")

        analysis_id = wait_for_compute_engine(ce_task_url, token)

        server_url = report.get("serverUrl") or effective_host_url
        report_project_key = report.get("projectKey") or effective_project_key
        gate = fetch_quality_gate(
            server_url, token, report_project_key, branch, analysis_id=analysis_id
        )
        project_status = gate.get("projectStatus", {})
        raw_status = project_status.get("status", "NONE")
        conditions = project_status.get("conditions", [])
        status, scoped_conditions = _evaluate_gate_status(conditions, scope=gate_scope)

        new_issues: List[SonarIssue] = []
        issues_stats: Dict[str, int] = {}
        if fetch_new_code_issues:
            if pull_request_key:
                new_issues, issues_stats = fetch_pull_request_issues(
                    server_url, token, report_project_key, pull_request_key
                )
            else:
                new_issues, issues_stats = fetch_new_issues(
                    server_url, token, report_project_key, branch
                )

    return SonarGateResult(
        status=status,
        raw_status=raw_status,
        conditions=scoped_conditions,
        issues=new_issues,
        issues_stats=issues_stats,
    )
