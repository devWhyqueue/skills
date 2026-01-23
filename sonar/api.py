from __future__ import annotations

import ast
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .http import _http_get_json, _http_get_json_with_params
from .models import SonarGateResult, SonarIssue
from .props import discover_report_task, read_project_properties, resolve_path
from .scan import run_scan


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
            if analysis_id:
                return str(analysis_id)
            raise RuntimeError("Compute engine returned SUCCESS without analysisId.")

        if last_status in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"Compute engine task failed: status={last_status}")

        time.sleep(1)

    raise RuntimeError(f"Compute engine task timed out. Last status: {last_status}")


def fetch_quality_gate(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    *,
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


def _fetch_issues(
    *,
    host_url: str,
    token: str,
    project_key: str,
    search_params: Dict[str, Any],
    page_size: int,
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
                "resolved": "false",
                "p": page,
                "ps": page_size,
                **search_params,
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
        "raw_count": raw_count,
        "issues": len(issues),
        "excluded_s138_decorated": excluded_s138_decorated,
    }


def fetch_new_issues(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    *,
    page_size: int = 500,
) -> tuple[List[SonarIssue], Dict[str, int]]:
    issues, stats = _fetch_issues(
        host_url=host_url,
        token=token,
        project_key=project_key,
        search_params={"branch": branch, "sinceLeakPeriod": "true"},
        page_size=page_size,
    )
    return issues, {
        "raw_new_issues": stats["raw_count"],
        "new_issues": stats["issues"],
        "excluded_s138_decorated": stats["excluded_s138_decorated"],
    }


def fetch_pull_request_issues(
    host_url: str,
    token: str,
    project_key: str,
    pull_request_key: str,
    *,
    page_size: int = 500,
) -> tuple[List[SonarIssue], Dict[str, int]]:
    issues, stats = _fetch_issues(
        host_url=host_url,
        token=token,
        project_key=project_key,
        search_params={"pullRequest": pull_request_key},
        page_size=page_size,
    )
    return issues, {
        "raw_pr_issues": stats["raw_count"],
        "pr_issues": stats["issues"],
        "excluded_s138_decorated": stats["excluded_s138_decorated"],
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


def run_gate_check(
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
    extra_args = [
        "--no-sonar-qualitygate-wait",
        f"-Dsonar.python.version={sys.version_info.major}.{sys.version_info.minor}",
    ]
    props = read_project_properties()
    effective_host_url = host_url or props.get("sonar.host.url")
    effective_project_key = project_key or props.get("sonar.projectKey")
    effective_sources = sources or props.get("sonar.sources") or "src"

    if not effective_host_url or not effective_project_key:
        raise RuntimeError(
            "Missing Sonar config. Provide `sonar-project.properties` with "
            "`sonar.host.url` and `sonar.projectKey`, or pass --sonar-host-url / --sonar-project-key."
        )

    with tempfile.TemporaryDirectory(prefix="clean-code-sonar-") as temp_dir:
        temp_path = Path(temp_dir)
        scanner_working_directory = temp_path / ".scannerwork"
        scanner_metadata_path = temp_path / "report-task.txt"

        p = run_scan(
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

        base_dir = Path.cwd()
        project_base = props.get("sonar.projectBaseDir")
        if project_base:
            base_dir = resolve_path(project_base, base_dir=base_dir)

        report, tried_paths = discover_report_task(
            base_dir=base_dir,
            props=props,
            scanner_metadata_path=scanner_metadata_path,
            scanner_working_directory=scanner_working_directory,
            temp_dir=temp_path,
        )
        if report is None:
            tried = "\n".join(f"- {c}" for c in tried_paths)
            raise RuntimeError(
                "Missing report-task.txt (pysonar output). Tried:\n"
                f"{tried}\n"
                f"pysonar exit={p.returncode}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
            )
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
