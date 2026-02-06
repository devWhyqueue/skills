from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional, Tuple

from git import current_branch
from sonar.models import SonarGateResult


def read_report_task(report_task_path: Path) -> Dict[str, str]:
    """Read report-task.txt and return key-value dict."""
    if report_task_path.name != "report-task.txt":
        raise RuntimeError(f"Expected a report-task.txt path, got: {report_task_path}")
    if not report_task_path.exists():
        raise RuntimeError(
            f"Missing report-task.txt (pysonar output): {report_task_path}"
        )

    data: Dict[str, str] = {}
    for line in report_task_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def resolve_path(value: str, *, base_dir: Path) -> Path:
    """
    Resolve a Sonar path-like property value to a concrete Path.

    Sonar properties may contain environment variables (e.g. %TEMP% / $TMP),
    tildes, and relative paths (typically relative to sonar.projectBaseDir).
    """
    expanded = os.path.expandvars((value or "").strip())
    expanded = os.path.expanduser(expanded)
    p = Path(expanded)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def strip_embedded_property(value: str, *, property_key: str) -> str:
    """Normalize env values like SONAR_HOST_URL=sonar.host.url=https://..."""
    v = (value or "").strip()
    prefix = f"{property_key}="
    return v[len(prefix) :].strip() if v.startswith(prefix) else v


def _env_host_project_sources(
    package_dir: Optional[Path],
    props: Dict[str, str],
    changed_files: Optional[list[str]] = None,
) -> Tuple[str, str, str]:
    """Resolve host, project, sources from env and props."""
    env_host = strip_embedded_property(
        os.getenv("SONAR_HOST_URL") or "", property_key="sonar.host.url"
    ).strip()
    env_proj = strip_embedded_property(
        os.getenv("SONAR_PROJECT_KEY") or "", property_key="sonar.projectKey"
    ).strip()
    prop_host = strip_embedded_property(
        props.get("sonar.host.url", ""), property_key="sonar.host.url"
    ).strip()
    prop_proj = strip_embedded_property(
        props.get("sonar.projectKey", ""), property_key="sonar.projectKey"
    ).strip()
    host = env_host or prop_host
    project = env_proj or prop_proj

    # Prefer restricting Sonar to changed files (already filtered by scope)
    # unless the user explicitly overrides via SONAR_SOURCES.
    env_sources = (os.getenv("SONAR_SOURCES") or "").strip()
    if env_sources:
        sources = env_sources
    elif changed_files:
        # Derive a minimal set of directories that contain the changed files.
        dirs = sorted({str(Path(f).parent) for f in changed_files})
        sources = ",".join(dirs)
    else:
        sources = package_dir.as_posix() if package_dir else ""
    return host, project, sources


def resolve_sonar_env(
    package_dir: Optional[Path],
    changed_files: Optional[list[str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], str]:
    """Resolve host, project, sources, token from env and props; return (host, project, sources, token, branch)."""
    sonar_token = (os.getenv("SONAR_TOKEN") or "").strip()
    if not sonar_token:
        return None, None, None, None, current_branch()
    props = read_project_properties()
    host, project, sources = _env_host_project_sources(
        package_dir, props, changed_files=changed_files
    )
    return (
        host or None,
        project or None,
        sources or None,
        sonar_token,
        current_branch(),
    )


def snapshot_sonar_artifacts() -> Dict[str, bool]:
    """Return existence snapshot of .sonar, .scannerwork, .ruff_cache."""
    paths = [Path(".sonar"), Path(".scannerwork"), Path(".ruff_cache")]
    return {str(p): p.exists() for p in paths}


def cleanup_sonar_artifacts(snapshot: Dict[str, bool]) -> None:
    """Remove paths that did not exist before (from snapshot)."""
    for path_str, existed in snapshot.items():
        if existed:
            continue
        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def sonar_gate_misconfigured(
    host: Optional[str], project: Optional[str], token: Optional[str]
) -> Optional[Tuple[Dict[str, object], str, bool]]:
    """Return (report, msg, True) if config missing, else None."""
    if not token:
        return (
            {"status": "misconfigured"},
            "Sonar enabled but SONAR_TOKEN not provided (expected in the calling project's .env).",
            True,
        )
    if not host or not project:
        return (
            {"status": "misconfigured"},
            "Sonar enabled but sonar.host.url / sonar.projectKey missing (expected in sonar-project.properties or .env).",
            True,
        )
    return None


def build_sonar_report_dict(
    gate: SonarGateResult,
    branch: str,
    project_key: str,
    sources: str,
    reference_branch: str,
    gate_scope: str,
) -> Dict[str, object]:
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


def read_project_properties(
    path: Path = Path("sonar-project.properties"),
) -> Dict[str, str]:
    """Read sonar-project.properties into a key-value dict."""
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


def _ensure_report_task_path(path: Path) -> Path:
    return path / "report-task.txt" if path.is_dir() else path


def _report_task_candidates(
    base_dir: Path,
    props: Dict[str, str],
    scanner_metadata_path: Optional[Path],
    scanner_working_directory: Optional[Path],
    temp_dir: Optional[Path],
) -> list[Path]:
    """Build list of candidate report-task paths."""
    candidates: list[Path] = []

    def _add(p: Optional[Path]) -> None:
        if p is None:
            return
        path = _ensure_report_task_path(p)
        if path not in candidates:
            candidates.append(path)

    _add(scanner_metadata_path)
    _add(scanner_working_directory)
    _add(temp_dir)
    metadata_value = props.get("sonar.scanner.metadataFilePath")
    if metadata_value:
        _add(resolve_path(metadata_value, base_dir=base_dir))
    workdir_value = props.get("sonar.working.directory")
    if workdir_value:
        _add(resolve_path(workdir_value, base_dir=base_dir))
    _add(base_dir / ".sonar" / "report-task.txt")
    _add(base_dir / ".scannerwork" / "report-task.txt")
    return candidates


def discover_report_task(
    *,
    base_dir: Path,
    props: Dict[str, str],
    scanner_metadata_path: Optional[Path],
    scanner_working_directory: Optional[Path],
    temp_dir: Optional[Path],
) -> Tuple[Optional[Dict[str, str]], list[Path]]:
    """Find report-task.txt from candidates; return (data, candidates) or (None, candidates)."""
    candidates = _report_task_candidates(
        base_dir, props, scanner_metadata_path, scanner_working_directory, temp_dir
    )
    for candidate in candidates:
        try:
            return read_report_task(candidate), candidates
        except (OSError, ValueError, RuntimeError):
            continue
    return None, candidates


__all__ = [
    "build_sonar_report_dict",
    "cleanup_sonar_artifacts",
    "discover_report_task",
    "read_project_properties",
    "read_report_task",
    "resolve_path",
    "resolve_sonar_env",
    "snapshot_sonar_artifacts",
    "sonar_gate_misconfigured",
    "strip_embedded_property",
]
