from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from sonar.gate_check import run_gate_check
from sonar.http import SonarGateResult
from sonar.props import (
    cleanup_sonar_artifacts,
    resolve_sonar_env,
    snapshot_sonar_artifacts,
    sonar_gate_misconfigured,
)

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


def build_sonar_report_dict(
    gate: SonarGateResult,
    branch: str,
    project_key: str,
    sources: str,
    reference_branch: str,
    gate_scope: str,
) -> dict[str, object]:
    """Build the sonar_report dict for run_sonar_gate."""
    return {
        "quality_gate": gate.status,
        "quality_gate_raw": gate.raw_status,
        "conditions": gate.conditions,
        "new_issues": [asdict(i) for i in gate.issues],
        "new_issues_stats": gate.issues_stats,
        "branch": branch,
        "reference_branch": reference_branch,
        "gate_scope": gate_scope,
        "pull_request_key": None,
        "pull_request_mode": False,
        "project_key": project_key,
        "sources": sources or "AUTO",
    }
