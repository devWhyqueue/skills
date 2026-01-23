from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple


def read_report_task(report_task_path: Path) -> Dict[str, str]:
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


def read_project_properties(
    path: Path = Path("sonar-project.properties"),
) -> Dict[str, str]:
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


def discover_report_task(
    *,
    base_dir: Path,
    props: Dict[str, str],
    scanner_metadata_path: Optional[Path],
    scanner_working_directory: Optional[Path],
    temp_dir: Optional[Path],
) -> Tuple[Optional[Dict[str, str]], list[Path]]:
    candidates: list[Path] = []

    def add(p: Optional[Path]) -> None:
        if p is None:
            return
        path = _ensure_report_task_path(p)
        if path not in candidates:
            candidates.append(path)

    add(scanner_metadata_path)
    add(scanner_working_directory)
    add(temp_dir)

    metadata_value = props.get("sonar.scanner.metadataFilePath")
    if metadata_value:
        add(resolve_path(metadata_value, base_dir=base_dir))

    workdir_value = props.get("sonar.working.directory")
    if workdir_value:
        add(resolve_path(workdir_value, base_dir=base_dir))

    add(base_dir / ".sonar" / "report-task.txt")
    add(base_dir / ".scannerwork" / "report-task.txt")

    for candidate in candidates:
        try:
            return read_report_task(candidate), candidates
        except Exception:
            continue

    return None, candidates


__all__ = [
    "discover_report_task",
    "read_project_properties",
    "read_report_task",
    "resolve_path",
]
