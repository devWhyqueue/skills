#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from audit import audit_changed_python_files, detect_base_ref
from fix import fix_files
from sonar import run_sonar_gate_check


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines into os.environ if missing."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def git_has_changes() -> bool:
    p = run(["git", "status", "--porcelain"])
    return bool(p.stdout.strip())


def git_current_branch() -> str:
    p = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    b = p.stdout.strip()
    return b if b else "unknown"


def ensure_clean_working_tree() -> None:
    if git_has_changes():
        raise RuntimeError(
            "Working tree is not clean. Commit/stash your current changes before running this skill."
        )


def git_commit(message: str) -> None:
    run(["git", "add", "-A"])
    p = run(["git", "commit", "-m", message])
    if p.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{p.stderr}")


def find_package_root(path: Path) -> Optional[Path]:
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def derive_scope_from_files(files: List[str]) -> str:
    scopes: List[str] = []

    for f in files:
        p = Path(f)
        parts = p.parts

        # src/<scope>/...
        if len(parts) >= 2 and parts[0] == "src":
            scopes.append(parts[1])
            continue

        # nearest package
        pkg_root = find_package_root(p)
        if pkg_root is not None:
            scopes.append(pkg_root.name)
            continue

        # fallback: first folder
        if len(parts) >= 2:
            scopes.append(parts[0])
        else:
            scopes.append("core")

    unique = sorted(set(s for s in scopes if s))
    if not unique:
        return "core"
    if len(unique) == 1:
        return unique[0]
    return "multi"


def main() -> int:
    import argparse

    load_env_file(Path(__file__).with_name(".sonar.env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--scope", default="AUTO")  # AUTO = derive from changed files
    ap.add_argument("--audit-only", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--max-iterations", type=int, default=2)

    # Sonar integration (gate only)
    ap.add_argument("--sonar", action="store_true", help="Run pysonar locally and enforce Quality Gate")
    ap.add_argument("--sonar-project-key", default=os.getenv("SONAR_PROJECT_KEY", "dwh-data-pipelines"))
    ap.add_argument("--sonar-host-url", default=os.getenv("SONAR_HOST_URL", ""))
    ap.add_argument("--sonar-token", default=os.getenv("SONAR_TOKEN", ""))
    ap.add_argument("--sonar-sources", default=os.getenv("SONAR_SOURCES", "src"))

    args = ap.parse_args()

    try:
        if not args.audit_only:
            ensure_clean_working_tree()

        fixed_files: List[str] = []
        all_violations = []

        files, violations = audit_changed_python_files(args.base, args.head)
        all_violations = violations

        if args.audit_only:
            status = "pass" if not any(v.severity == "error" for v in violations) else "fail"
            report = {
                "status": status,
                "changed_files": files,
                "fixed_files": [],
                "violations": [asdict(v) for v in violations],
                "sonar": None,
                "summary": "Audit-only run.",
            }
            print(json.dumps(report, indent=2))
            return 0 if status == "pass" else 2

        # Fix loop
        for _ in range(args.max_iterations):
            if not files:
                break

            fix_results = fix_files(files)
            fixed_now = [r.file for r in fix_results if r.changed]
            fixed_files.extend(fixed_now)

            files, violations = audit_changed_python_files(args.base, args.head)
            all_violations = violations

            if not any(v.severity == "error" for v in violations):
                break

        clean_code_ok = not any(v.severity == "error" for v in all_violations)
        status = "pass" if clean_code_ok else "fail"
        summary = "All clean code checks passed." if clean_code_ok else "Remaining violations require semantic refactor."

        # Determine scope
        if args.scope.upper() == "AUTO":
            scope = derive_scope_from_files(files)
        else:
            scope = args.scope

        # Sonar gate (only after clean code errors are resolved)
        sonar_report = None
        if clean_code_ok and args.sonar:
            if not args.sonar_host_url or not args.sonar_token:
                status = "fail"
                summary = "Sonar enabled but SONAR_HOST_URL / SONAR_TOKEN not provided."
                sonar_report = {"status": "misconfigured"}
            else:
                branch = git_current_branch()
                gate = run_sonar_gate_check(
                    host_url=args.sonar_host_url,
                    token=args.sonar_token,
                    project_key=args.sonar_project_key,
                    branch=branch,
                    sources=args.sonar_sources,
                )
                sonar_report = {
                    "quality_gate": gate.status,
                    "conditions": gate.conditions,
                    "branch": branch,
                    "project_key": args.sonar_project_key,
                    "sources": args.sonar_sources,
                }
                if gate.status != "OK":
                    status = "fail"
                    summary = f"SonarQube Quality Gate failed: {gate.status}"

        # Commit if all gates pass + requested + changes exist
        commit_msg = f"refactor({scope}): clean code compliance"
        committed = False
        if status == "pass" and args.commit and git_has_changes():
            git_commit(commit_msg)
            committed = True

        report: Dict = {
            "status": status,
            "changed_files": files,
            "fixed_files": sorted(set(fixed_files)),
            "violations": [asdict(v) for v in all_violations],
            "sonar": sonar_report,
            "commit": {"attempted": args.commit, "created": committed, "message": commit_msg if committed else None},
            "summary": summary,
            "scope": scope,
            "next_action": (
                "Fix remaining violations (Codex should edit the files), then re-run this skill."
                if status == "fail"
                else "Done."
            ),
        }

        print(json.dumps(report, indent=2))
        return 0 if status == "pass" else 2

    except Exception as e:
        report = {
            "status": "fail",
            "summary": f"Internal error: {type(e).__name__}: {e}",
        }
        print(json.dumps(report, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
