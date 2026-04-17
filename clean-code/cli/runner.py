from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from cli.scope import derive_scope_from_files, resolve_package_dir
from audit import audit_python_files
from audit.files import exclude_test_folders, filter_python_files, is_within_dir
from audit.fix import fix_files
from git import uncommitted_changed_files
from semantic.gate import default_semantic_out_dir, reset_semantic_out_dir, run_semantic_gate_if_enabled

from cli.gates import run_gates
from cli.helpers import semantic_failure_summary

logger = logging.getLogger(__name__)
SEMANTIC_CACHE_FILENAME = "pipeline_report.json"


def _print_report(report: dict[str, Any]) -> None:
    logger.info(json.dumps(report, indent=2))


def _resolve_package_dir(scope: str) -> Optional[Path]:
    if not str(scope).strip() or str(scope).strip().upper() == "AUTO":
        return None
    return resolve_package_dir(scope)


def _list_changed_python_files(*, package_dir: Optional[Path]) -> list[str]:
    files = exclude_test_folders(filter_python_files(uncommitted_changed_files()))
    if package_dir is not None:
        files = [f for f in files if is_within_dir(Path(f), package_dir)]
    return files


def _run_fix_loop(
    args: SimpleNamespace, files: list[str], *, package_dir: Optional[Path]
) -> tuple[list[str], list[Any], list[str]]:
    fixed_files: list[str] = []
    files, violations = audit_python_files(files, package_dir=package_dir)

    for _ in range(int(args.max_iterations)):
        if not files:
            break

        fix_results = fix_files(files)
        fixed_now = [r.file for r in fix_results if r.changed]
        fixed_files.extend(fixed_now)

        files, violations = audit_python_files(files, package_dir=package_dir)
        if not violations:
            break

    return files, violations, fixed_files


def _duration_from_report(report: Any) -> Optional[float]:
    if not isinstance(report, dict):
        return None
    duration = report.get("duration_sec")
    if isinstance(duration, (int, float)):
        return float(duration)
    return None


def _stage_durations(
    *,
    audit_duration_sec: Optional[float] = None,
    vulture_report: Any = None,
    pyright_report: Any = None,
    pytest_report: Any = None,
    sonar_report: Any = None,
    semantic_report: Any = None,
    existing: Optional[dict[str, Any]] = None,
) -> dict[str, float]:
    durations: dict[str, float] = {}
    if isinstance(existing, dict):
        for stage, value in existing.items():
            if isinstance(value, (int, float)):
                durations[str(stage)] = float(value)
    if audit_duration_sec is not None:
        durations["audit"] = audit_duration_sec
    for stage_name, report in (
        ("vulture", vulture_report),
        ("pyright", pyright_report),
        ("pytest", pytest_report),
        ("sonar", sonar_report),
        ("semantic", semantic_report),
    ):
        duration = _duration_from_report(report)
        if duration is not None:
            durations[stage_name] = duration
    return durations


def _next_action(status: str, semantic_report: Any) -> str:
    if status != "fail":
        return "Done."
    if isinstance(semantic_report, dict) and semantic_report.get("status") in {
        "requires_reviewer",
        "pending",
    }:
        return (
            "Semantic review required: address items in semantic_ledger.yml "
            "(or provide evaluated ledger output), then re-run this skill."
        )
    return "Fix remaining violations (Codex should edit the files), then re-run this skill."


def _semantic_cache_path() -> Path:
    return default_semantic_out_dir() / SEMANTIC_CACHE_FILENAME


def _load_cached_report() -> Optional[dict[str, Any]]:
    cache_path = _semantic_cache_path()
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_cached_report(report: dict[str, Any]) -> None:
    out_dir = default_semantic_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    _semantic_cache_path().write_text(json.dumps(report, indent=2), encoding="utf-8")


def _semantic_resume_available(args: SimpleNamespace) -> bool:
    if not getattr(args, "semantic", False):
        return False
    cached_report = _load_cached_report()
    if not isinstance(cached_report, dict):
        return False
    semantic_report = cached_report.get("semantic")
    if not isinstance(semantic_report, dict):
        return False
    return str(semantic_report.get("status", "")).strip() in {
        "pending",
        "requires_reviewer",
        "fail",
    }


def _run_semantic_resume(args: SimpleNamespace) -> tuple[int, dict[str, Any]]:
    package_dir = _resolve_package_dir(args.scope)
    files = _list_changed_python_files(package_dir=package_dir)
    cached_report = _load_cached_report() or {}

    semantic_start = time.perf_counter()
    semantic_report = run_semantic_gate_if_enabled(enabled=True, files=files)
    semantic_duration_sec = round(time.perf_counter() - semantic_start, 3)
    if isinstance(semantic_report, dict):
        semantic_report["duration_sec"] = semantic_duration_sec

    status = "pass"
    summary = "All clean code checks passed."
    if isinstance(semantic_report, dict):
        semantic_summary = semantic_failure_summary(semantic_report)
        if semantic_summary is not None:
            status = "fail"
            summary = semantic_summary

    scope = (
        package_dir.name if package_dir is not None else derive_scope_from_files(files)
    )
    report: dict[str, Any] = {
        "status": status,
        "changed_files": files,
        "fixed_files": cached_report.get("fixed_files", []),
        "violations": cached_report.get("violations", []),
        "vulture": cached_report.get("vulture"),
        "sonar": cached_report.get("sonar"),
        "pyright": cached_report.get("pyright"),
        "pytest": cached_report.get("pytest"),
        "semantic": semantic_report,
        "summary": summary,
        "scope": scope,
        "package": (package_dir.as_posix() if package_dir is not None else None),
        "next_action": _next_action(status, semantic_report),
        "pipeline_mode": "semantic_resume",
        "stage_durations_sec": _stage_durations(
            semantic_report=semantic_report,
            existing=cached_report.get("stage_durations_sec"),
        ),
    }
    _write_cached_report(report)
    return (0 if status == "pass" else 2), report


def _run_full(args: SimpleNamespace) -> tuple[int, dict[str, Any]]:
    package_dir = _resolve_package_dir(args.scope)

    files = _list_changed_python_files(package_dir=package_dir)

    fixed_files: list[str] = []
    violations: list[Any] = []
    audit_duration_sec: Optional[float] = None
    if args.audit:
        audit_start = time.perf_counter()
        files, violations, fixed_files = _run_fix_loop(
            args, files, package_dir=package_dir
        )
        audit_duration_sec = round(time.perf_counter() - audit_start, 3)

    clean_code_ok = not violations
    status = "pass" if clean_code_ok else "fail"
    summary = (
        "All clean code checks passed."
        if clean_code_ok
        else "Remaining violations require semantic refactor."
    )

    scope = (
        package_dir.name if package_dir is not None else derive_scope_from_files(files)
    )
    (
        status,
        summary,
        vulture_report,
        pyright_report,
        pytest_report,
        sonar_report,
        semantic_report,
    ) = run_gates(args, files, package_dir, status, summary)
    report: dict[str, Any] = {
        "status": status,
        "changed_files": files,
        "fixed_files": sorted(set(fixed_files)),
        "violations": [asdict(v) for v in violations],
        "vulture": vulture_report,
        "sonar": sonar_report,
        "pyright": pyright_report,
        "pytest": pytest_report,
        "semantic": semantic_report,
        "summary": summary,
        "scope": scope,
        "package": (package_dir.as_posix() if package_dir is not None else None),
        "next_action": _next_action(status, semantic_report),
        "pipeline_mode": "full",
        "stage_durations_sec": _stage_durations(
            audit_duration_sec=audit_duration_sec,
            vulture_report=vulture_report,
            pyright_report=pyright_report,
            pytest_report=pytest_report,
            sonar_report=sonar_report,
            semantic_report=semantic_report,
        ),
    }

    return (0 if status == "pass" else 2), report


def _run_all_stages(args: SimpleNamespace) -> tuple[int, dict[str, Any]]:
    return _run_full(args)


def run(args: SimpleNamespace) -> int:
    """Run the full skill pipeline (audit, pyright, vulture, optional sonar/semantic). Returns 0/2/3."""
    try:
        args.max_iterations = 5
        args.audit = True
        args.vulture = True
        args.pyright = True
        args.pytest = True
        args.sonar = not getattr(args, "minimal", False)
        args.semantic = not getattr(args, "minimal", False)
        resume_semantic = _semantic_resume_available(args)
        if args.semantic and not resume_semantic:
            reset_semantic_out_dir()
        if resume_semantic:
            code, report = _run_semantic_resume(args)
            if code != 0:
                _print_report(report)
                return code
        code, report = _run_all_stages(args)
        if args.semantic:
            _write_cached_report(report)
        _print_report(report)
        return code
    except Exception as e:
        _print_report(
            {"status": "fail", "summary": f"Internal error: {type(e).__name__}: {e}"}
        )
        return 3
