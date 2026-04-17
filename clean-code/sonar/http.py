from __future__ import annotations

import ast
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import truststore

try:
    truststore.inject_into_ssl()
except (ImportError, AttributeError, RuntimeError, OSError):
    pass

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # seconds


@dataclass
class SonarIssue:
    key: str
    rule: str
    severity: str
    message: str
    component: str
    line: Optional[int]
    type: str

    def __repr__(self) -> str:
        return (
            f"SonarIssue(key={self.key!r}, rule={self.rule!r}, severity={self.severity!r}, "
            f"message={self.message!r}, component={self.component!r}, line={self.line!r}, type={self.type!r})"
        )


@dataclass
class SonarGateResult:
    status: str
    raw_status: str
    conditions: List[Dict[str, Any]]
    issues: List[SonarIssue]
    issues_stats: Dict[str, int]


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
    """True if line is in a function decorated with @dag or @task_group (filter python:S138)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
        if start is None or end is None or not (start <= line <= end):
            continue
        for dec in node.decorator_list:
            if _is_airflow_dag_or_task_group_decorator(dec):
                return True
    return False


def _http_get_json(url: str, token: str) -> Dict[str, Any]:
    """GET *url* with token auth and return parsed JSON."""
    resp = requests.get(
        url,
        auth=(token, ""),
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _http_get_json_with_params(
    base_url: str, token: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{base_url}?{urllib.parse.urlencode({**params, '_ts': time.time_ns()})}"
    return _http_get_json(url, token)
