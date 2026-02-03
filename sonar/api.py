from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

from .http import _http_get_json_with_params
from .models import SonarIssue


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


def fetch_quality_gate(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    *,
    analysis_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch quality gate project status from SonarQube API."""
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
    """Return list of pull requests for the project from SonarQube API."""
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
                except (OSError, ValueError):
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
    """Fetch new-code issues for branch from SonarQube API."""
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
    """Fetch issues for a pull request from SonarQube API."""
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
