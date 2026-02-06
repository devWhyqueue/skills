from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sonar.api import (
    fetch_new_issues,
    fetch_pull_request_issues,
    fetch_quality_gate,
    poll_ce_task,
)
from sonar.models import SonarGateResult, SonarIssue
from sonar.props import (
    build_sonar_report_dict,
    cleanup_sonar_artifacts,
    discover_report_task,
    read_project_properties,
    resolve_sonar_env,
    snapshot_sonar_artifacts,
    sonar_gate_misconfigured,
)
from sonar.scan import run_scan

logger = logging.getLogger(__name__)

DEFAULT_REFERENCE_BRANCH = "develop"
DEFAULT_GATE_SCOPE = "new-code"


def _run_gate_with_artifacts(
    host: str,
    project: str,
    sources: Optional[str],
    token: str,
    branch: str,
) -> SonarGateResult:
    """Snapshot artifacts, run_gate_check, cleanup; return gate result."""
    artifact_snapshot = snapshot_sonar_artifacts()
    try:
        return run_gate_check(
            token=token,
            branch=branch,
            reference_branch=DEFAULT_REFERENCE_BRANCH,
            gate_scope=DEFAULT_GATE_SCOPE,
            pull_request_key=None,
            pull_request_branch=branch,
            pull_request_base=DEFAULT_REFERENCE_BRANCH,
            host_url=host,
            project_key=project,
            sources=sources,
        )
    finally:
        cleanup_sonar_artifacts(artifact_snapshot)


def _sonar_gate_result(
    gate: SonarGateResult, report: dict[str, object]
) -> tuple[dict[str, object], Optional[str], bool]:
    """Return (report, fail_msg or None, failed)."""
    if gate.status == "NONE" and DEFAULT_GATE_SCOPE == "new-code":
        msg = (
            "SonarQube new-code gate could not be evaluated: no new-code (new_*) gate conditions found. "
            "Add new-code conditions to the Quality Gate (or change the skill's DEFAULT_GATE_SCOPE)."
        )
        return (report, msg, True)
    if gate.status != "OK":
        return (report, f"SonarQube Quality Gate failed: {gate.status}", True)
    return (report, None, False)


def run_sonar_gate(
    *,
    enabled: bool,
    package_dir: Optional[Path],
    changed_files: Optional[list[str]] = None,
) -> tuple[Optional[dict[str, object]], Optional[str], bool]:
    """Run Sonar quality gate; return (report, error_summary, failed)."""
    if not enabled:
        return None, None, False
    host, project, sources, token, branch = resolve_sonar_env(
        package_dir, changed_files=changed_files
    )
    if err := sonar_gate_misconfigured(host, project, token):
        return err
    assert host is not None and project is not None and token is not None
    gate = _run_gate_with_artifacts(host, project, sources, token, branch)
    report = build_sonar_report_dict(
        gate,
        branch,
        project or "",
        sources or "",
        DEFAULT_REFERENCE_BRANCH,
        DEFAULT_GATE_SCOPE,
    )
    return _sonar_gate_result(gate, report)


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


def _run_scan_for_gate(
    token: str,
    branch: str,
    effective_host_url: str,
    effective_project_key: str,
    effective_sources: str,
    *,
    reference_branch: Optional[str] = None,
    pull_request_key: Optional[str] = None,
    pull_request_branch: Optional[str] = None,
    pull_request_base: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Run pysonar scan; return report-task.txt data dict (or None)."""
    extra_args = [
        f"-Dsonar.python.version={sys.version_info.major}.{sys.version_info.minor}",
    ]
    run_scan(
        token=token,
        branch=branch,
        reference_branch=reference_branch,
        scanner_metadata_path=None,
        scanner_working_directory=None,
        pull_request_key=pull_request_key,
        pull_request_branch=pull_request_branch,
        pull_request_base=pull_request_base,
        host_url=effective_host_url,
        project_key=effective_project_key,
        sources=effective_sources,
        extra_args=extra_args,
    )
    # Try to locate report-task.txt so we can poll the CE task.
    props = read_project_properties()
    base_dir = Path.cwd()
    project_base = props.get("sonar.projectBaseDir")
    if project_base:
        from sonar.props import resolve_path

        base_dir = resolve_path(project_base, base_dir=base_dir)
    report_data, _ = discover_report_task(
        base_dir=base_dir,
        props=props,
        scanner_metadata_path=None,
        scanner_working_directory=None,
        temp_dir=None,
    )
    return report_data


def _collect_new_issues(
    effective_host_url: str,
    token: str,
    effective_project_key: str,
    pull_request_key: Optional[str],
    branch: str,
) -> Tuple[List[SonarIssue], Dict[str, int]]:
    if pull_request_key:
        return fetch_pull_request_issues(
            effective_host_url, token, effective_project_key, pull_request_key
        )
    return fetch_new_issues(effective_host_url, token, effective_project_key, branch)


def _effective_gate_config(
    host_url: Optional[str],
    project_key: Optional[str],
    sources: Optional[str],
) -> Tuple[str, str, str]:
    """Resolve effective host, project, sources; raise if missing."""
    props = read_project_properties()
    host = host_url or props.get("sonar.host.url")
    project = project_key or props.get("sonar.projectKey")
    src = sources or props.get("sonar.sources") or "src"
    if not host or not project:
        raise RuntimeError(
            "Missing Sonar config. Provide `sonar-project.properties` with "
            "`sonar.host.url` and `sonar.projectKey`, or pass --sonar-host-url / --sonar-project-key."
        )
    return str(host), str(project), str(src)


def _fetch_gate_result(
    host_url: str,
    token: str,
    project_key: str,
    branch: str,
    gate_scope: str,
    fetch_new_code_issues: bool,
    pull_request_key: Optional[str],
    analysis_id: Optional[str] = None,
) -> SonarGateResult:
    """Fetch quality gate status and optional new issues; return SonarGateResult."""
    gate = fetch_quality_gate(
        host_url, token, project_key, branch, analysis_id=analysis_id
    )
    project_status = gate.get("projectStatus", {}) or {}
    raw_status = str(project_status.get("status", "NONE"))
    conditions = project_status.get("conditions", []) or []
    status, scoped_conditions = _evaluate_gate_status(
        conditions if isinstance(conditions, list) else [], scope=gate_scope
    )
    new_issues: List[SonarIssue] = []
    issues_stats: Dict[str, int] = {}
    if fetch_new_code_issues:
        new_issues, issues_stats = _collect_new_issues(
            host_url, token, project_key, pull_request_key, branch
        )
    return SonarGateResult(
        status=status,
        raw_status=raw_status,
        conditions=scoped_conditions,
        issues=new_issues,
        issues_stats=issues_stats,
    )


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
    """Run Sonar scan, wait for analysis, fetch quality gate and optional new-code issues."""
    effective_host_url, effective_project_key, effective_sources = (
        _effective_gate_config(host_url, project_key, sources)
    )
    report_data = _run_scan_for_gate(
        token,
        branch,
        effective_host_url,
        effective_project_key,
        effective_sources,
        reference_branch=reference_branch,
        pull_request_key=pull_request_key,
        pull_request_branch=pull_request_branch,
        pull_request_base=pull_request_base,
    )

    # Wait for the SonarQube server to finish processing the analysis.
    analysis_id: Optional[str] = None
    ce_task_url = (report_data or {}).get("ceTaskUrl")
    if ce_task_url:
        logger.info("Waiting for SonarQube analysis to complete (%s)...", ce_task_url)
        task = poll_ce_task(ce_task_url, token)
        analysis_id = task.get("analysisId")
    else:
        logger.warning(
            "Could not locate ceTaskUrl in report-task.txt; "
            "fetching quality gate without waiting for analysis."
        )

    return _fetch_gate_result(
        effective_host_url,
        token,
        effective_project_key,
        branch,
        gate_scope,
        fetch_new_code_issues,
        pull_request_key,
        analysis_id=analysis_id,
    )
