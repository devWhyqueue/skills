from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .http import (
    _component_path,
    _http_get_json,
    _http_get_json_with_params,
    _is_exempt_from_sonar_s138,
    SonarIssue,
)

logger = logging.getLogger(__name__)


def _poll_ce_task_step(
    ce_task_url: str, token: str, deadline: float, timeout: int, interval: int
) -> tuple[bool, Dict[str, Any]]:
    """Poll once; return (True, task) if done, (False, {}) if need to retry."""
    payload = _http_get_json(ce_task_url, token)
    task = payload.get("task", {})
    status = str(task.get("status", "")).upper()
    logger.debug("CE task status: %s", status)
    if status in {"SUCCESS", "FAILED", "CANCELED"}:
        if status != "SUCCESS":
            raise RuntimeError(
                f"SonarQube analysis task {status}: {task.get('errorMessage', 'no details')}"
            )
        return True, task
    if time.monotonic() >= deadline:
        raise RuntimeError(
            f"Timed out ({timeout}s) waiting for SonarQube analysis (last status: {status})."
        )
    time.sleep(interval)
    return False, {}


def poll_ce_task(
    ce_task_url: str,
    token: str,
    *,
    timeout: int = 300,
    interval: int = 5,
) -> Dict[str, Any]:
    """Poll the SonarQube Compute Engine task until it completes or times out.

    Args:
        ce_task_url: Full URL to the ``/api/ce/task`` endpoint (from report-task.txt ``ceTaskUrl``).
        token: SonarQube auth token.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.

    Returns:
        The ``task`` dict from the API response.

    Raises:
        RuntimeError: If the task fails, is cancelled, or polling times out.
    """
    deadline = time.monotonic() + timeout
    while True:
        done, task = _poll_ce_task_step(ce_task_url, token, deadline, timeout, interval)
        if done:
            return task


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
