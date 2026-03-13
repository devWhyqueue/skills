"""Run pipeline gates (vulture, pyright, pytest, sonar, semantic). Extracted to keep runner under 250 lines."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from pytest_gate.gate import run_pytest_gate
from sonar.gate import run_sonar_gate
from typecheck.gate import run_pyright_gate
from vulture_gate.gate import run_vulture_gate

from cli.helpers import semantic_failure_summary
from semantic.gate import run_semantic_gate_if_enabled


def _timed_gate_result(
    gate_fn: Any,
    /,
    **kwargs: Any,
) -> tuple[Any, Optional[str], bool]:
    start = time.perf_counter()
    report, summary, failed = gate_fn(**kwargs)
    duration_sec = round(time.perf_counter() - start, 3)
    if isinstance(report, dict):
        report["duration_sec"] = duration_sec
    return report, summary, failed


def _timed_semantic_report(*, enabled: bool, files: list[str]) -> Any:
    start = time.perf_counter()
    report = run_semantic_gate_if_enabled(enabled=enabled, files=files)
    duration_sec = round(time.perf_counter() - start, 3)
    if isinstance(report, dict):
        report["duration_sec"] = duration_sec
    return report


def _run_vulture_pyright_pytest(
    args: SimpleNamespace,
    files: list[str],
    package_dir: Optional[Path],
    status: str,
    summary: str,
) -> tuple[str, str, Any, Any, Any]:
    """Run vulture, pyright, pytest; return (status, summary, vulture_report, pyright_report, pytest_report)."""
    vulture_report, pyright_report, pytest_report = None, None, None
    if args.vulture:
        vulture_report, s, failed = _timed_gate_result(
            run_vulture_gate,
            enabled=True, changed_files=files, package_dir=package_dir
        )
        if failed and status == "pass":
            status, summary = "fail", s or summary
    if status == "pass":
        pyright_report, s, failed = _timed_gate_result(
            run_pyright_gate,
            enabled=bool(args.pyright), changed_files=files
        )
        if failed:
            status, summary = "fail", s or summary
    if status == "pass":
        coverage_fail_under = getattr(args, "min_coverage", None) or 0
        pytest_report, s, failed = _timed_gate_result(
            run_pytest_gate,
            enabled=bool(args.pytest),
            changed_files=files,
            package_dir=package_dir,
            coverage_fail_under=coverage_fail_under,
        )
        if failed:
            status, summary = "fail", s or summary
    return status, summary, vulture_report, pyright_report, pytest_report


def _run_sonar_semantic(
    args: SimpleNamespace,
    files: list[str],
    package_dir: Optional[Path],
    status: str,
    summary: str,
) -> tuple[str, str, Any, Any]:
    """Run sonar and semantic; return (status, summary, sonar_report, semantic_report)."""
    sonar_report, semantic_report = None, None
    if status == "pass":
        sonar_report, s, failed = _timed_gate_result(
            run_sonar_gate,
            enabled=bool(args.sonar), package_dir=package_dir, changed_files=files
        )
        if failed:
            status, summary = "fail", s or summary
    if status == "pass":
        semantic_report = _timed_semantic_report(enabled=bool(args.semantic), files=files)
        if isinstance(semantic_report, dict):
            sem_summary = semantic_failure_summary(semantic_report)
            if sem_summary is not None:
                status, summary = "fail", sem_summary
    return status, summary, sonar_report, semantic_report


def run_gates(
    args: SimpleNamespace,
    files: list[str],
    package_dir: Optional[Path],
    status: str,
    summary: str,
) -> tuple[str, str, Any, Any, Any, Any, Any]:
    """Run vulture, pyright, pytest, sonar, semantic in order; return (status, summary, reports...)."""
    status, summary, vulture_report, pyright_report, pytest_report = (
        _run_vulture_pyright_pytest(args, files, package_dir, status, summary)
    )
    status, summary, sonar_report, semantic_report = _run_sonar_semantic(
        args, files, package_dir, status, summary
    )
    return (
        status,
        summary,
        vulture_report,
        pyright_report,
        pytest_report,
        sonar_report,
        semantic_report,
    )
