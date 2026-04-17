"""Sonar scan, wait for analysis, and fetch quality gate. Split out to keep gate.py under 250 lines."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sonar.api import (
    fetch_new_issues,
    fetch_pull_request_issues,
    fetch_quality_gate,
    poll_ce_task,
)
from sonar.http import SonarGateResult, SonarIssue
from sonar.props import discover_report_task, read_project_properties, resolve_path
from sonar.scan import run_scan

logger = logging.getLogger(__name__)


def _sonar_temp_base_dir() -> Path:
    """Return the base temp dir for Sonar scratch data."""
    configured = (os.getenv("SONAR_TMPDIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name != "nt":
        return Path("/tmp")
    return Path(tempfile.gettempdir()).resolve()


def _split_csv_paths(value: Optional[str]) -> list[str]:
    """Split comma-delimited Sonar path lists, dropping empty entries."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _copy_analysis_inputs(
    *,
    temp_dir: Path,
    effective_sources: str,
    effective_inclusions: Optional[str],
) -> tuple[Optional[Path], str, Optional[str], str]:
    """Create a slim project tree for file-scoped scans, else fall back.

    The Python coverage sensor resolves report paths by walking the project
    base dir. On mounted workspaces with large repo-root directories
    (.venv/.sonar/etc.), that can dominate the scan. For changed-file mode we
    copy only the explicit source files and coverage.xml into a temp project.
    """
    source_entries = _split_csv_paths(effective_sources)
    if not source_entries:
        return None, effective_sources, effective_inclusions, "coverage.xml"

    source_paths = [Path(entry) for entry in source_entries]
    if any(path.is_absolute() or not path.is_file() for path in source_paths):
        return None, effective_sources, effective_inclusions, "coverage.xml"

    project_dir = temp_dir / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_paths:
        target = project_dir / source_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)

    coverage_src = Path("coverage.xml")
    if coverage_src.is_file():
        shutil.copy2(coverage_src, project_dir / "coverage.xml")

    inclusion_entries = _split_csv_paths(effective_inclusions)
    slim_inclusions = (
        ",".join(inclusion_entries)
        if inclusion_entries and all(not Path(entry).is_absolute() for entry in inclusion_entries)
        else effective_inclusions
    )
    return project_dir, ",".join(source_entries), slim_inclusions, "coverage.xml"


def _run_scan_for_gate(
    token: str,
    branch: str,
    effective_host_url: str,
    effective_project_key: str,
    effective_sources: str,
    effective_inclusions: Optional[str],
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
    temp_root = _sonar_temp_base_dir()
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="clean-code-sonar-",
        dir=temp_root,
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        (
            project_base_dir,
            scan_sources,
            scan_inclusions,
            coverage_report_path,
        ) = _copy_analysis_inputs(
            temp_dir=temp_dir,
            effective_sources=effective_sources,
            effective_inclusions=effective_inclusions,
        )
        scanner_working_directory = temp_dir / "workdir"
        scanner_working_directory.mkdir(parents=True, exist_ok=True)
        scanner_metadata_path = temp_dir / "report-task.txt"
        extra_args.append(f"-Dsonar.python.coverage.reportPaths={coverage_report_path}")
        run_scan(
            token=token,
            branch=branch,
            reference_branch=reference_branch,
            project_base_dir=project_base_dir,
            scanner_metadata_path=scanner_metadata_path,
            scanner_working_directory=scanner_working_directory,
            pull_request_key=pull_request_key,
            pull_request_branch=pull_request_branch,
            pull_request_base=pull_request_base,
            host_url=effective_host_url,
            project_key=effective_project_key,
            sources=scan_sources,
            inclusions=scan_inclusions,
            extra_args=extra_args,
        )
        props = read_project_properties()
        base_dir = project_base_dir or Path.cwd()
        project_base = props.get("sonar.projectBaseDir")
        if project_base and project_base_dir is None:
            base_dir = resolve_path(project_base, base_dir=base_dir)
        report_data, _ = discover_report_task(
            base_dir=base_dir,
            props=props,
            scanner_metadata_path=scanner_metadata_path,
            scanner_working_directory=scanner_working_directory,
            temp_dir=temp_dir,
        )
        return report_data


def _wait_for_analysis(
    report_data: Optional[Dict[str, str]], token: str
) -> Optional[str]:
    """Poll CE task from report_data; return analysis_id when done."""
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
    return analysis_id


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
    if fetch_new_code_issues and status != "OK":
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
    inclusions: Optional[str] = None,
) -> SonarGateResult:
    """Run Sonar scan, wait for analysis, fetch quality gate and optional new-code issues."""
    e_host, e_project, e_sources = _effective_gate_config(
        host_url, project_key, sources
    )
    report_data = _run_scan_for_gate(
        token,
        branch,
        e_host,
        e_project,
        e_sources,
        inclusions,
        reference_branch=reference_branch,
        pull_request_key=pull_request_key,
        pull_request_branch=pull_request_branch,
        pull_request_base=pull_request_base,
    )
    return _fetch_gate_result(
        e_host,
        token,
        e_project,
        branch,
        gate_scope,
        fetch_new_code_issues,
        pull_request_key,
        analysis_id=_wait_for_analysis(report_data, token),
    )
