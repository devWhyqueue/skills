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


def git_changed_paths() -> List[str]:
    """
    Return a list of changed paths in the working tree (including untracked).
    Uses `--porcelain=v1 -z` to handle whitespace and renames robustly.
    """
    p = run(["git", "status", "--porcelain=v1", "-z"])
    if p.returncode != 0:
        raise RuntimeError(f"git status failed:\n{p.stderr}")

    out = p.stdout
    if not out:
        return []

    entries = out.split("\0")
    paths: List[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        if not entry:
            i += 1
            continue

        # Format: XY SP PATH  (PATH may be followed by NUL NEWPATH for renames/copies)
        status = entry[:2]
        rest = entry[3:] if len(entry) >= 4 else ""
        if rest:
            paths.append(rest)

        if status and status[0] in {"R", "C"}:
            if i + 1 < len(entries) and entries[i + 1]:
                paths.append(entries[i + 1])
            i += 2
        else:
            i += 1

    return paths


def ensure_clean_working_tree(allowed_dirty_paths: Optional[List[str]] = None) -> None:
    changed = git_changed_paths()
    if not changed:
        return

    allowed = set(allowed_dirty_paths or [])
    if allowed and all(p in allowed for p in changed):
        return

    msg = "Working tree is not clean."
    if allowed:
        msg += " Unrelated changes detected outside the PR-changed Python files."
    msg += " Commit/stash your current changes before running this skill."
    raise RuntimeError(msg)


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

    # Load per-project secrets/config from the calling project's root (CWD).
    load_env_file(Path.cwd() / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--scope", default="AUTO")  # AUTO = derive from changed files
    ap.add_argument("--audit-only", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--max-iterations", type=int, default=2)

    # Sonar integration (gate only)
    ap.add_argument("--sonar", action="store_true", help="Run pysonar locally and enforce Quality Gate")
    ap.add_argument("--sonar-project-key", default=os.getenv("SONAR_PROJECT_KEY", ""))
    ap.add_argument("--sonar-host-url", default=os.getenv("SONAR_HOST_URL", ""))
    ap.add_argument("--sonar-token", default=os.getenv("SONAR_TOKEN", ""))
    ap.add_argument("--sonar-sources", default=os.getenv("SONAR_SOURCES", ""))

    args = ap.parse_args()

    try:
        fixed_files: List[str] = []
        all_violations = []

        files, violations = audit_changed_python_files(args.base, args.head)
        all_violations = violations

        if not args.audit_only:
            ensure_clean_working_tree(allowed_dirty_paths=files)

        if args.audit_only:
            status = "pass" if not violations else "fail"
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

            if not violations:
                break

        clean_code_ok = not all_violations
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
            if not args.sonar_token:
                status = "fail"
                summary = "Sonar enabled but SONAR_TOKEN not provided (expected in the calling project's .env)."
                sonar_report = {"status": "misconfigured"}
            else:
                branch = git_current_branch()
                gate = run_sonar_gate_check(
                    token=args.sonar_token,
                    branch=branch,
                    host_url=args.sonar_host_url or None,
                    project_key=args.sonar_project_key or None,
                    sources=args.sonar_sources or None,
                )
                sonar_report = {
                    "quality_gate": gate.status,
                    "conditions": gate.conditions,
                    "branch": branch,
                    "project_key": args.sonar_project_key or "AUTO",
                    "sources": args.sonar_sources or "AUTO",
                }
                if gate.status != "OK":
                    status = "fail"
                    summary = f"SonarQube Quality Gate failed: {gate.status}"

        # Commit if all gates pass + requested + changes exist
        commit_msg = f"refactor({scope}): clean code compliance"
        committed = False
        if status == "pass" and args.commit and git_has_changes():
            ensure_clean_working_tree(allowed_dirty_paths=files)
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
