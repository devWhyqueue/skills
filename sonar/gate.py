from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from git import current_branch
from sonar import run_gate_check
from sonar.artifacts import cleanup_sonar_artifacts, snapshot_sonar_artifacts
from sonar.props import read_project_properties

DEFAULT_REFERENCE_BRANCH = "develop"
DEFAULT_GATE_SCOPE = "new-code"


def run_sonar_gate(
    *,
    enabled: bool,
    package_dir: Optional[Path],
) -> tuple[Optional[dict[str, object]], Optional[str], bool]:
    if not enabled:
        return None, None, False

    sonar_token = (os.getenv("SONAR_TOKEN") or "").strip()
    if not sonar_token:
        return (
            {"status": "misconfigured"},
            "Sonar enabled but SONAR_TOKEN not provided (expected in the calling project's .env).",
            True,
        )

    props = read_project_properties()
    branch = current_branch()
    reference_branch = DEFAULT_REFERENCE_BRANCH

    effective_host_url = (os.getenv("SONAR_HOST_URL") or "").strip() or props.get(
        "sonar.host.url", ""
    )
    effective_project_key = (os.getenv("SONAR_PROJECT_KEY") or "").strip() or props.get(
        "sonar.projectKey", ""
    )
    if not effective_host_url or not effective_project_key:
        return (
            {"status": "misconfigured"},
            "Sonar enabled but sonar.host.url / sonar.projectKey missing (expected in sonar-project.properties or .env).",
            True,
        )

    sonar_sources_env = (os.getenv("SONAR_SOURCES") or "").strip()
    effective_sources = sonar_sources_env or (
        package_dir.as_posix() if package_dir else ""
    )
    artifact_snapshot = snapshot_sonar_artifacts()
    try:
        gate = run_gate_check(
            token=sonar_token,
            branch=branch,
            reference_branch=reference_branch,
            gate_scope=DEFAULT_GATE_SCOPE,
            pull_request_key=None,
            pull_request_branch=branch,
            pull_request_base=reference_branch,
            host_url=effective_host_url,
            project_key=effective_project_key,
            sources=effective_sources or None,
        )
    finally:
        cleanup_sonar_artifacts(artifact_snapshot)

    sonar_report: dict[str, object] = {
        "quality_gate": gate.status,
        "quality_gate_raw": gate.raw_status,
        "conditions": gate.conditions,
        "new_issues": [asdict(i) for i in gate.issues],
        "new_issues_stats": gate.issues_stats,
        "branch": branch,
        "reference_branch": reference_branch,
        "gate_scope": DEFAULT_GATE_SCOPE,
        "pull_request_key": None,
        "pull_request_mode": False,
        "project_key": effective_project_key,
        "sources": effective_sources or "AUTO",
    }

    if gate.status == "NONE" and DEFAULT_GATE_SCOPE == "new-code":
        return (
            sonar_report,
            "SonarQube new-code gate could not be evaluated: no new-code (new_*) gate conditions found. "
            "Add new-code conditions to the Quality Gate (or change the skill's DEFAULT_GATE_SCOPE).",
            True,
        )
    if gate.status != "OK":
        return (
            sonar_report,
            f"SonarQube Quality Gate failed: {gate.status}",
            True,
        )

    return sonar_report, None, False
