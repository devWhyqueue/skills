from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from cli.scope import derive_scope_from_files, resolve_package_dir
from audit import audit_python_files
from audit.files import exclude_test_folders, filter_python_files, is_within_dir
from audit.fix import fix_files
from git import uncommitted_changed_files
from semantic.gate import reset_semantic_out_dir, run_semantic_gate_if_enabled
from sonar.gate import run_sonar_gate
from typecheck.gate import run_pyright_gate
from vulture_gate.gate import run_vulture_gate

logger = logging.getLogger(__name__)


def _semantic_failure_message(
    status: str, fails: int, needs_human: int, ledger_path: object
) -> str:
    if status == "pending":
        return (
            "Semantic ledger pending evaluation. "
            f"Review '{ledger_path}' and the per-file ledgers it references, set PASS/FAIL/NA "
            "(NEEDS_HUMAN only if truly undecidable), then re-run."
        )
    if status == "requires_reviewer":
        return (
            f"Semantic gate requires reviewer input: fails={fails}, needs_human={needs_human} "
            f"(ledger: {ledger_path})."
        )
    return f"Semantic gate failed: fails={fails}, needs_human={needs_human} (ledger: {ledger_path})."


def semantic_failure_summary(semantic_report: dict[str, Any]) -> Optional[str]:
    """Return a short summary string if semantic gate failed; otherwise None."""
    sem_status = str(semantic_report.get("status", "")).strip()
    if sem_status in {"", "pass"}:
        return None
    sem_summary = (
        semantic_report.get("summary", {}) if isinstance(semantic_report, dict) else {}
    )
    sem_fails = int(sem_summary.get("fails", 0) or 0)
    sem_needs = int(sem_summary.get("needs_human", 0) or 0)
    ledger_path = semantic_report.get("ledger_path")
    return _semantic_failure_message(sem_status, sem_fails, sem_needs, ledger_path)


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


def _run_full(args: SimpleNamespace) -> tuple[int, dict[str, Any]]:
    package_dir = _resolve_package_dir(args.scope)

    files = _list_changed_python_files(package_dir=package_dir)

    fixed_files: list[str] = []
    violations: list[Any] = []
    if args.audit:
        files, violations, fixed_files = _run_fix_loop(
            args, files, package_dir=package_dir
        )

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

    vulture_report = None
    sonar_report = None
    pyright_report = None
    if args.vulture:
        vulture_report, vulture_summary, vulture_failed = run_vulture_gate(
            enabled=bool(args.vulture),
            changed_files=files,
        )
        if vulture_failed and status == "pass":
            status = "fail"
            summary = vulture_summary or summary

    if status == "pass":
        pyright_report, pyright_summary, pyright_failed = run_pyright_gate(
            enabled=bool(args.pyright),
            package_dir=package_dir,
        )
        if pyright_failed:
            status = "fail"
            summary = pyright_summary or summary

    if status == "pass":
        sonar_report, sonar_summary, sonar_failed = run_sonar_gate(
            enabled=bool(args.sonar),
            package_dir=package_dir,
        )
        if sonar_failed:
            status = "fail"
            summary = sonar_summary or summary

    semantic_report = None
    if status == "pass":
        semantic_report = run_semantic_gate_if_enabled(
            enabled=bool(args.semantic),
            files=files,
        )
        if isinstance(semantic_report, dict):
            sem_summary = semantic_failure_summary(semantic_report)
            if sem_summary is not None:
                status = "fail"
                summary = sem_summary

    report: dict[str, Any] = {
        "status": status,
        "changed_files": files,
        "fixed_files": sorted(set(fixed_files)),
        "violations": [asdict(v) for v in violations],
        "vulture": vulture_report,
        "sonar": sonar_report,
        "pyright": pyright_report,
        "semantic": semantic_report,
        "summary": summary,
        "scope": scope,
        "package": (package_dir.as_posix() if package_dir is not None else None),
        "next_action": (
            (
                "Semantic review required: address items in semantic_ledger.yml (or provide evaluated ledger output), then re-run this skill."
                if (
                    status == "fail"
                    and isinstance(semantic_report, dict)
                    and semantic_report.get("status")
                    in {"requires_reviewer", "pending"}
                )
                else "Fix remaining violations (Codex should edit the files), then re-run this skill."
            )
            if status == "fail"
            else "Done."
        ),
    }

    return (0 if status == "pass" else 2), report


def _clone_args(args: SimpleNamespace, **overrides: object) -> SimpleNamespace:
    base = vars(args).copy()
    base.update(overrides)
    return SimpleNamespace(**base)


def _run_all_stages(args: SimpleNamespace) -> tuple[int, dict[str, Any]]:
    code, report = _run_full(
        _clone_args(args, audit=True, pyright=False, sonar=False, semantic=False)
    )
    if code != 0:
        return code, report
    code, report = _run_full(
        _clone_args(args, audit=True, pyright=True, sonar=False, semantic=False)
    )
    if code != 0:
        return code, report
    if getattr(args, "minimal", False):
        return code, report
    code, report = _run_full(
        _clone_args(args, audit=True, pyright=True, sonar=True, semantic=False)
    )
    if code != 0:
        return code, report
    code, report = _run_full(
        _clone_args(args, audit=True, pyright=True, sonar=True, semantic=True)
    )
    return code, report


def run(args: SimpleNamespace) -> int:
    """Run the full skill pipeline (audit, pyright, vulture, optional sonar/semantic). Returns 0/2/3."""
    try:
        args.max_iterations = 5
        args.audit = True
        args.vulture = True
        args.pyright = True
        args.sonar = not getattr(args, "minimal", False)
        args.semantic = not getattr(args, "minimal", False)
        reset_semantic_out_dir()
        code, report = _run_all_stages(args)
        _print_report(report)
        return code
    except Exception as e:
        _print_report(
            {"status": "fail", "summary": f"Internal error: {type(e).__name__}: {e}"}
        )
        return 3
