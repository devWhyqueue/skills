"""Persist and resume semantic-gate progress."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from cli.helpers import semantic_failure_summary
from cli.scope import derive_scope_from_files
from semantic.gate import default_semantic_out_dir, run_semantic_gate_if_enabled

SEMANTIC_CACHE_FILENAME = "pipeline_report.json"


def write_cached_report(report: dict[str, Any]) -> None:
    """Write a report beside the semantic ledger for the current branch."""
    out_dir = default_semantic_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    _cache_path().write_text(json.dumps(report, indent=2), encoding="utf-8")


def semantic_resume_available(args: SimpleNamespace) -> bool:
    """Return whether a previous semantic review can continue."""
    if not getattr(args, "semantic", False):
        return False
    semantic_report = (_load_cached_report() or {}).get("semantic")
    if not isinstance(semantic_report, dict):
        return False
    return str(semantic_report.get("status", "")).strip() in {
        "pending",
        "requires_reviewer",
        "fail",
    }


def run_semantic_resume(
    *, package_dir: Optional[Path], files: list[str]
) -> tuple[int, dict[str, Any]]:
    """Evaluate the next semantic batch and merge it with its cached report."""
    cached_report = _load_cached_report() or {}
    semantic_report = _run_semantic_gate(files)
    status, summary = _semantic_status(semantic_report)
    scope = (
        package_dir.name if package_dir is not None else derive_scope_from_files(files)
    )
    report = _resume_report(cached_report, semantic_report, status, summary)
    report.update(
        {"changed_files": files, "scope": scope, "package": _package(package_dir)}
    )
    write_cached_report(report)
    return (0 if status == "pass" else 2), report


def _cache_path() -> Path:
    return default_semantic_out_dir() / SEMANTIC_CACHE_FILENAME


def _load_cached_report() -> Optional[dict[str, Any]]:
    cache_path = _cache_path()
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _run_semantic_gate(files: list[str]) -> Any:
    start = time.perf_counter()
    report = run_semantic_gate_if_enabled(enabled=True, files=files)
    if isinstance(report, dict):
        report["duration_sec"] = round(time.perf_counter() - start, 3)
    return report


def _semantic_status(report: Any) -> tuple[str, str]:
    if not isinstance(report, dict):
        return "pass", "All clean code checks passed."
    summary = semantic_failure_summary(report)
    return (
        ("fail", summary)
        if summary is not None
        else ("pass", "All clean code checks passed.")
    )


def _resume_report(
    cached: dict[str, Any], semantic: Any, status: str, summary: str
) -> dict[str, Any]:
    durations = _durations(cached.get("stage_durations_sec"), semantic)
    return {
        "status": status,
        "fixed_files": cached.get("fixed_files", []),
        "violations": cached.get("violations", []),
        "vulture": cached.get("vulture"),
        "sonar": cached.get("sonar"),
        "pyright": cached.get("pyright"),
        "pytest": cached.get("pytest"),
        "semantic": semantic,
        "summary": summary,
        "next_action": _next_action(status, semantic),
        "pipeline_mode": "semantic_resume",
        "stage_durations_sec": durations,
    }


def _durations(existing: object, semantic: Any) -> dict[str, float]:
    durations = (
        {
            str(key): float(value)
            for key, value in (existing or {}).items()
            if isinstance(value, (int, float))
        }
        if isinstance(existing, dict)
        else {}
    )
    if isinstance(semantic, dict) and isinstance(
        semantic.get("duration_sec"), (int, float)
    ):
        durations["semantic"] = float(semantic["duration_sec"])
    return durations


def _next_action(status: str, semantic: Any) -> str:
    if status != "fail":
        return "Done."
    if isinstance(semantic, dict) and semantic.get("status") in {
        "requires_reviewer",
        "pending",
    }:
        return "Semantic review required: address items in semantic_ledger.yml, then re-run this skill."
    return "Fix remaining violations, then re-run this skill."


def _package(package_dir: Optional[Path]) -> Optional[str]:
    return package_dir.as_posix() if package_dir is not None else None
