from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from audit import audit_changed_python_files
from audit.files import filter_python_files, is_within_dir
from git import changed_files, detect_base_ref
from cli.scope import derive_scope_from_files, resolve_package_dir
from semantic.gate import run_semantic_gate_if_enabled
from sonar.gate import run_sonar_gate
from audit.fix import fix_files
from git import commit as git_commit
from git import ensure_clean_working_tree, has_changes


def semantic_failure_summary(semantic_report: dict[str, Any]) -> Optional[str]:
    sem_status = str(semantic_report.get("status", "")).strip()
    if sem_status in {"", "pass"}:
        return None

    sem_summary = (
        semantic_report.get("summary", {}) if isinstance(semantic_report, dict) else {}
    )
    sem_fails = int(sem_summary.get("fails", 0) or 0)
    sem_needs = int(sem_summary.get("needs_human", 0) or 0)
    ledger_path = semantic_report.get("ledger_path")

    if sem_status == "pending":
        return (
            "Semantic ledger pending evaluation. "
            f"Review '{ledger_path}', set PASS/FAIL/NA for each entry "
            "(NEEDS_HUMAN only if truly undecidable), then re-run."
        )
    if sem_status == "requires_reviewer":
        return (
            f"Semantic gate requires reviewer input: fails={sem_fails}, needs_human={sem_needs} "
            f"(ledger: {ledger_path})."
        )
    return (
        f"Semantic gate failed: fails={sem_fails}, needs_human={sem_needs} "
        f"(ledger: {ledger_path})."
    )


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2))


def _resolve_package_dir(scope: str) -> Optional[Path]:
    if not str(scope).strip() or str(scope).strip().upper() == "AUTO":
        return None
    return resolve_package_dir(scope)


def _list_changed_python_files(
    *, base_ref: str, head_ref: str, package_dir: Optional[Path]
) -> list[str]:
    files = filter_python_files(changed_files(base_ref, head_ref))
    if package_dir is not None:
        files = [f for f in files if is_within_dir(Path(f), package_dir)]
    return files


def _run_fix_loop(
    args: Any, *, package_dir: Optional[Path]
) -> tuple[list[str], list[Any], list[str]]:
    fixed_files: list[str] = []
    files, violations = audit_changed_python_files(
        args.base_ref, args.head_ref, package_dir=package_dir
    )

    for _ in range(int(args.max_iterations)):
        if not files:
            break

        fix_results = fix_files(files)
        fixed_now = [r.file for r in fix_results if r.changed]
        fixed_files.extend(fixed_now)

        files, violations = audit_changed_python_files(
            args.base_ref, args.head_ref, package_dir=package_dir
        )
        if not violations:
            break

    return files, violations, fixed_files


def _full_run(args: Any) -> int:
    package_dir = _resolve_package_dir(args.scope)

    files = _list_changed_python_files(
        base_ref=args.base_ref, head_ref=args.head_ref, package_dir=package_dir
    )

    fixed_files: list[str] = []
    violations: list[Any] = []
    if args.audit:
        ensure_clean_working_tree(allowed_dirty_paths=files, ignore_untracked=True)
        files, violations, fixed_files = _run_fix_loop(args, package_dir=package_dir)

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

    sonar_report = None
    if status == "pass":
        sonar_report, sonar_summary, sonar_failed = run_sonar_gate(
            enabled=bool(args.sonar),
            package_dir=package_dir,
        )
        if sonar_failed:
            status = "fail"
            summary = sonar_summary or summary

    commit_msg = f"refactor({scope}): clean code compliance"
    committed = False

    semantic_report = None
    if status == "pass":
        semantic_report = run_semantic_gate_if_enabled(
            enabled=bool(args.semantic),
            files=files,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        if isinstance(semantic_report, dict):
            sem_summary = semantic_failure_summary(semantic_report)
            if sem_summary is not None:
                status = "fail"
                summary = sem_summary

    commit_enabled = bool(args.commit) and bool(args.audit)
    if status == "pass" and commit_enabled and has_changes():
        ensure_clean_working_tree(allowed_dirty_paths=files, ignore_untracked=True)
        git_commit(commit_msg, paths=files)
        committed = True

    report: dict[str, Any] = {
        "status": status,
        "changed_files": files,
        "fixed_files": sorted(set(fixed_files)),
        "violations": [asdict(v) for v in violations],
        "sonar": sonar_report,
        "semantic": semantic_report,
        "commit": {
            "attempted": bool(commit_enabled),
            "created": committed,
            "message": commit_msg if committed else None,
        },
        "summary": summary,
        "scope": scope,
        "package": (package_dir.as_posix() if package_dir is not None else None),
        "next_action": (
            (
                "Semantic review required: address items in semantic_ledger.yml (or provide evaluated ledger output), then re-run this skill."
                if (
                    status == "fail"
                    and isinstance(semantic_report, dict)
                    and semantic_report.get("status") == "requires_human"
                )
                else "Fix remaining violations (Codex should edit the files), then re-run this skill."
            )
            if status == "fail"
            else "Done."
        ),
    }

    _print_report(report)
    return 0 if status == "pass" else 2


def run(args: Any) -> int:
    try:
        base_ref = detect_base_ref("develop")
        args.base_ref = base_ref
        args.head_ref = "HEAD"
        args.max_iterations = 5
        return _full_run(args)
    except Exception as e:
        _print_report(
            {
                "status": "fail",
                "summary": f"Internal error: {type(e).__name__}: {e}",
            }
        )
        return 3
