#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from audit import audit_changed_python_files, detect_base_ref
from fix import fix_files
from semantic_gate import load_and_validate_ledger, run_semantic_scaffold
from sonar import fetch_project_pull_requests, run_sonar_gate_check


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
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def git_has_changes() -> bool:
    p = run(["git", "status", "--porcelain"])
    return bool(p.stdout.strip())


def git_current_branch() -> str:
    p = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    b = p.stdout.strip()
    return b if b else "unknown"


def default_semantic_out_dir() -> Path:
    """
    Use a stable temp directory per git branch so a human/Codex can edit the
    semantic ledger and rerun without losing the file.
    """
    branch = git_current_branch()
    safe = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in branch
    )
    return Path(tempfile.gettempdir()) / f"clean-code-pr-review-semantic-{safe}"


def git_status_entries() -> List[tuple[str, str]]:
    """
    Return (status, path) entries in the working tree (including untracked).
    Uses `--porcelain=v1 -z` to handle whitespace and renames robustly.
    """
    p = run(["git", "status", "--porcelain=v1", "-z"])
    if p.returncode != 0:
        raise RuntimeError(f"git status failed:\n{p.stderr}")

    out = p.stdout
    if not out:
        return []

    entries = out.split("\0")
    results: List[tuple[str, str]] = []
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
            results.append((status, rest))

        if status and status[0] in {"R", "C"}:
            if i + 1 < len(entries) and entries[i + 1]:
                results.append((status, entries[i + 1]))
            i += 2
        else:
            i += 1

    return results


def git_changed_paths() -> List[str]:
    return [path for _, path in git_status_entries()]


def ensure_clean_working_tree(
    allowed_dirty_paths: Optional[List[str]] = None,
    *,
    ignore_untracked: bool = False,
) -> None:
    entries = git_status_entries()
    if ignore_untracked:
        entries = [e for e in entries if e[0] != "??"]

    if not entries:
        return

    allowed = set(allowed_dirty_paths or [])
    if allowed and all(path in allowed for _, path in entries):
        return

    msg = "Working tree is not clean."
    if allowed:
        msg += " Unrelated changes detected outside the PR-changed Python files."
    msg += " Commit/stash your current changes before running this skill."
    raise RuntimeError(msg)


def git_commit(message: str, *, paths: Optional[List[str]] = None) -> None:
    if paths:
        run(["git", "add", "--", *paths])
    else:
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


def normalize_package_value(value: str) -> str:
    v = (value or "").strip()
    v = v.replace("\\", "/")
    v = v.strip("/")
    v = v.replace(".", "/")
    return v


def git_ls_files() -> List[str]:
    p = run(["git", "ls-files"])
    if p.returncode != 0:
        return []
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def resolve_package_dir(value: str) -> Path:
    """
    Resolve a user-provided package value into a directory path.

    Supported values:
    - "abc" (package name)
    - "src/abc" (path)
    - "abc.def" (dotted path => "abc/def")
    """
    normalized = normalize_package_value(value)
    if not normalized:
        raise ValueError("Package must be a non-empty string.")

    candidates: List[Path] = [Path(normalized)]
    if not normalized.startswith("src/"):
        candidates.append(Path("src") / Path(normalized))

    for cand in candidates:
        if cand.exists() and cand.is_dir():
            return cand

    suffix = f"/{normalized}/__init__.py"
    matches = [p for p in git_ls_files() if p.endswith(suffix)]
    unique_dirs = sorted({str(Path(m).parent) for m in matches})

    if len(unique_dirs) == 1:
        return Path(unique_dirs[0])
    if len(unique_dirs) > 1:
        examples = ", ".join(d.replace("\\", "/") for d in unique_dirs[:5])
        all_matches = "\n".join(f"- {d.replace('\\', '/')}" for d in unique_dirs)
        raise RuntimeError(
            f"Package '{value}' is ambiguous; found multiple matches: {examples}.\n"
            f"Pass a more specific package path, for example one of:\n{all_matches}\n"
            f"Tip: dotted paths are supported (e.g. 'data_pipelines.dags.{Path(normalized).name}')."
        )

    raise RuntimeError(
        f"Could not resolve package '{value}'. Provide a package name or a package path "
        f"(e.g. '{normalized}' or 'src/{normalized}')."
    )


def normalize_sonar_reference_branch(value: str) -> str:
    """
    Best-effort normalization for Sonar's reference branch name.

    Examples:
    - "develop" -> "develop"
    - "origin/develop" -> "develop"
    """
    v = (value or "").strip()
    if not v:
        return "develop"
    if "/" in v:
        return v.rsplit("/", 1)[-1]
    return v


def read_sonar_project_properties(
    path: Path = Path("sonar-project.properties"),
) -> dict[str, str]:
    if not path.exists():
        return {}
    props: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if key:
            props[key] = v.strip()
    return props


def detect_pull_request_key(
    *,
    sonar_host_url: str,
    sonar_token: str,
    sonar_project_key: str,
    branch: str,
) -> Optional[str]:
    prs = fetch_project_pull_requests(sonar_host_url, sonar_token, sonar_project_key)
    for pr in prs:
        if str(pr.get("branch", "")).strip() == branch:
            key = str(pr.get("key", "")).strip()
            return key if key else None
    return None


def snapshot_sonar_artifacts() -> Dict[str, bool]:
    paths = [Path(".sonar"), Path(".scannerwork"), Path(".ruff_cache")]
    return {str(p): p.exists() for p in paths}


def cleanup_sonar_artifacts(snapshot: Dict[str, bool]) -> None:
    for path_str, existed in snapshot.items():
        if existed:
            continue

        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


def main() -> int:
    import argparse

    # Load per-project secrets/config from the calling project's root (CWD).
    load_env_file(Path.cwd() / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument(
        "--scope",
        default="AUTO",
        help="Target package to audit/fix (name or path). AUTO = all changed Python files.",
    )
    ap.add_argument("--audit-only", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--max-iterations", type=int, default=2)

    semantic_group = ap.add_mutually_exclusive_group()
    semantic_group.add_argument(
        "--semantic",
        dest="semantic",
        action="store_true",
        help="Enable SEMANTIC rules compliance ledger (YAML) and gate on it (default).",
    )
    semantic_group.add_argument(
        "--no-semantic",
        dest="semantic",
        action="store_false",
        help="Disable semantic gate.",
    )
    ap.set_defaults(semantic=None)
    ap.add_argument(
        "--semantic-rules",
        default="clean_code_rules.yml",
        help="Path to rules YAML for SEMANTIC gate (default: clean_code_rules.yml).",
    )
    ap.add_argument(
        "--semantic-max-diff-chars",
        type=int,
        default=int(os.getenv("SEMANTIC_MAX_DIFF_CHARS", "120000")),
        help="Maximum characters of diff per file included in the semantic prompt.",
    )
    ap.add_argument(
        "--semantic-scaffold-only",
        action="store_true",
        help="Only generate semantic_prompt.md + semantic_ledger.yml scaffold (no gating).",
    )
    ap.add_argument(
        "--semantic-out-dir",
        default=os.getenv("SEMANTIC_OUT_DIR", ""),
        help="Directory for semantic artifacts (prompt + ledger). Default: a stable temp folder per git branch.",
    )

    # Sonar integration (gate only)
    ap.add_argument(
        "--no-sonar",
        action="store_true",
        help="Disable SonarQube Quality Gate enforcement (enabled by default).",
    )
    ap.add_argument("--sonar-project-key", default=os.getenv("SONAR_PROJECT_KEY", ""))
    ap.add_argument("--sonar-host-url", default=os.getenv("SONAR_HOST_URL", ""))
    ap.add_argument("--sonar-token", default=os.getenv("SONAR_TOKEN", ""))
    ap.add_argument("--sonar-sources", default=os.getenv("SONAR_SOURCES", ""))
    ap.add_argument(
        "--sonar-gate-scope",
        choices=["new-code", "full"],
        default=os.getenv("SONAR_GATE_SCOPE", "new-code"),
        help="Quality gate scope: 'new-code' (PR-scoped) or 'full' (server-reported).",
    )
    ap.add_argument(
        "--sonar-reference-branch",
        default=os.getenv("SONAR_REFERENCE_BRANCH", "develop"),
        help="Sonar new-code reference branch (default: develop).",
    )
    ap.add_argument(
        "--sonar-pull-request",
        action="store_true",
        help="Run Sonar in pull request mode (auto-detect PR key for the current branch).",
    )
    ap.add_argument(
        "--sonar-pull-request-key",
        default=os.getenv("SONAR_PULL_REQUEST_KEY", ""),
        help="Explicit Sonar PR key (skips auto-detection).",
    )
    ap.add_argument(
        "--sonar-pull-request-base",
        default=os.getenv("SONAR_PULL_REQUEST_BASE", ""),
        help="Explicit Sonar PR base branch (default: --sonar-reference-branch).",
    )
    ap.add_argument(
        "--sonar-pull-request-branch",
        default=os.getenv("SONAR_PULL_REQUEST_BRANCH", ""),
        help="Explicit Sonar PR branch name (default: current git branch).",
    )

    args = ap.parse_args()
    if args.semantic_scaffold_only and args.semantic is False:
        raise RuntimeError("--semantic-scaffold-only conflicts with --no-semantic")

    if args.semantic is None:
        args.semantic = bool(args.commit) and not bool(args.audit_only)
    if args.semantic_scaffold_only:
        args.semantic = True

    try:
        fixed_files: List[str] = []
        all_violations = []
        sonar_enabled = not args.no_sonar

        package_dir: Optional[Path] = None
        if str(args.scope).strip().upper() != "AUTO":
            package_dir = resolve_package_dir(args.scope)

        files, violations = audit_changed_python_files(
            args.base, args.head, package_dir=package_dir
        )
        all_violations = violations

        if not args.audit_only:
            ensure_clean_working_tree(allowed_dirty_paths=files, ignore_untracked=True)

        if args.audit_only:
            status = "pass" if not violations else "fail"
            summary = (
                "Audit-only run."
                if files
                else (
                    f"Audit-only run: no changed Python files in scope '{args.scope}'."
                    if package_dir is not None
                    else "Audit-only run: no changed Python files."
                )
            )

            sonar_report = None
            if sonar_enabled:
                if not args.sonar_token:
                    status = "fail"
                    summary = "Sonar enabled but SONAR_TOKEN not provided (expected in the calling project's .env)."
                    sonar_report = {"status": "misconfigured"}
                else:
                    props = read_sonar_project_properties()
                    branch = git_current_branch()
                    reference_branch = normalize_sonar_reference_branch(
                        args.sonar_reference_branch
                    )
                    effective_host_url = args.sonar_host_url or props.get(
                        "sonar.host.url", ""
                    )
                    effective_project_key = args.sonar_project_key or props.get(
                        "sonar.projectKey", ""
                    )

                    pull_request_key = None
                    run_sonar = True
                    if args.sonar_pull_request:
                        if not effective_host_url or not effective_project_key:
                            status = "fail"
                            summary = "Sonar PR mode requires sonar.host.url and sonar.projectKey."
                            sonar_report = {"status": "misconfigured"}
                            run_sonar = False
                        else:
                            pull_request_key = (
                                args.sonar_pull_request_key.strip() or None
                            )
                            if not pull_request_key:
                                pull_request_key = detect_pull_request_key(
                                    sonar_host_url=effective_host_url,
                                    sonar_token=args.sonar_token,
                                    sonar_project_key=effective_project_key,
                                    branch=branch,
                                )
                            if not pull_request_key:
                                status = "fail"
                                summary = f"Sonar PR mode enabled, but no PR found on server for branch '{branch}'."
                                sonar_report = {
                                    "status": "pr_not_found",
                                    "branch": branch,
                                }
                                run_sonar = False

                    if run_sonar:
                        effective_sources = args.sonar_sources or (
                            package_dir.as_posix() if package_dir else ""
                        )
                        artifact_snapshot = snapshot_sonar_artifacts()
                        try:
                            gate = run_sonar_gate_check(
                                token=args.sonar_token,
                                branch=branch,
                                reference_branch=reference_branch,
                                gate_scope=args.sonar_gate_scope,
                                pull_request_key=pull_request_key,
                                pull_request_branch=(
                                    args.sonar_pull_request_branch.strip() or branch
                                ),
                                pull_request_base=(
                                    args.sonar_pull_request_base.strip()
                                    or reference_branch
                                ),
                                host_url=args.sonar_host_url or None,
                                project_key=args.sonar_project_key or None,
                                sources=effective_sources or None,
                            )
                        finally:
                            cleanup_sonar_artifacts(artifact_snapshot)

                        sonar_report = {
                            "quality_gate": gate.status,
                            "quality_gate_raw": gate.raw_status,
                            "conditions": gate.conditions,
                            "new_issues": [asdict(i) for i in gate.issues],
                            "new_issues_stats": gate.issues_stats,
                            "branch": branch,
                            "reference_branch": reference_branch,
                            "gate_scope": args.sonar_gate_scope,
                            "pull_request_key": pull_request_key,
                            "pull_request_mode": args.sonar_pull_request,
                            "project_key": args.sonar_project_key or "AUTO",
                            "sources": effective_sources or "AUTO",
                        }
                        if (
                            gate.status == "NONE"
                            and args.sonar_gate_scope == "new-code"
                        ):
                            status = "fail"
                            summary = (
                                "SonarQube PR-scoped gate could not be evaluated: no new-code (new_*) gate conditions found. "
                                "Add new-code conditions to the Quality Gate or run with --sonar-gate-scope full."
                            )
                        elif gate.status != "OK":
                            status = "fail"
                            summary = f"SonarQube Quality Gate failed: {gate.status}"

            report = {
                "status": status,
                "changed_files": files,
                "fixed_files": [],
                "violations": [asdict(v) for v in violations],
                "sonar": sonar_report,
                "commit": {"attempted": False, "created": False, "message": None},
                "summary": summary,
                "scope": (
                    package_dir.name
                    if package_dir is not None
                    else derive_scope_from_files(files)
                ),
                "package": (
                    package_dir.as_posix() if package_dir is not None else None
                ),
                "next_action": (
                    "Fix remaining violations (Codex should edit the files), then re-run this skill."
                    if status == "fail"
                    else "Done."
                ),
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

            files, violations = audit_changed_python_files(
                args.base, args.head, package_dir=package_dir
            )
            all_violations = violations

            if not violations:
                break

        clean_code_ok = not all_violations
        status = "pass" if clean_code_ok else "fail"
        summary = (
            "All clean code checks passed."
            if clean_code_ok
            else "Remaining violations require semantic refactor."
        )

        scope = (
            package_dir.name
            if package_dir is not None
            else derive_scope_from_files(files)
        )

        # Sonar gate (only after clean code errors are resolved)
        sonar_report = None
        if clean_code_ok and sonar_enabled:
            if not args.sonar_token:
                status = "fail"
                summary = "Sonar enabled but SONAR_TOKEN not provided (expected in the calling project's .env)."
                sonar_report = {"status": "misconfigured"}
            else:
                props = read_sonar_project_properties()
                branch = git_current_branch()
                reference_branch = normalize_sonar_reference_branch(
                    args.sonar_reference_branch
                )
                pull_request_key = None
                if args.sonar_pull_request:
                    effective_host_url = args.sonar_host_url or props.get(
                        "sonar.host.url", ""
                    )
                    effective_project_key = args.sonar_project_key or props.get(
                        "sonar.projectKey", ""
                    )
                    if not effective_host_url or not effective_project_key:
                        status = "fail"
                        summary = "Sonar PR mode requires sonar.host.url and sonar.projectKey."
                        sonar_report = {"status": "misconfigured"}
                    else:
                        pull_request_key = args.sonar_pull_request_key.strip() or None
                        if not pull_request_key:
                            pull_request_key = detect_pull_request_key(
                                sonar_host_url=effective_host_url,
                                sonar_token=args.sonar_token,
                                sonar_project_key=effective_project_key,
                                branch=branch,
                            )
                        if not pull_request_key:
                            status = "fail"
                            summary = f"Sonar PR mode enabled, but no PR found on server for branch '{branch}'."
                            sonar_report = {"status": "pr_not_found", "branch": branch}

                if not sonar_report:
                    effective_sources = args.sonar_sources or (
                        package_dir.as_posix() if package_dir else ""
                    )
                    artifact_snapshot = snapshot_sonar_artifacts()
                    try:
                        gate = run_sonar_gate_check(
                            token=args.sonar_token,
                            branch=branch,
                            reference_branch=reference_branch,
                            gate_scope=args.sonar_gate_scope,
                            pull_request_key=pull_request_key,
                            pull_request_branch=(
                                args.sonar_pull_request_branch.strip() or branch
                            ),
                            pull_request_base=(
                                args.sonar_pull_request_base.strip() or reference_branch
                            ),
                            host_url=args.sonar_host_url or None,
                            project_key=args.sonar_project_key or None,
                            sources=effective_sources or None,
                        )
                    finally:
                        cleanup_sonar_artifacts(artifact_snapshot)
                    sonar_report = {
                        "quality_gate": gate.status,
                        "quality_gate_raw": gate.raw_status,
                        "conditions": gate.conditions,
                        "new_issues": [asdict(i) for i in gate.issues],
                        "new_issues_stats": gate.issues_stats,
                        "branch": branch,
                        "reference_branch": reference_branch,
                        "gate_scope": args.sonar_gate_scope,
                        "pull_request_key": pull_request_key,
                        "pull_request_mode": args.sonar_pull_request,
                        "project_key": args.sonar_project_key or "AUTO",
                        "sources": effective_sources or "AUTO",
                    }
                    if gate.status == "NONE" and args.sonar_gate_scope == "new-code":
                        status = "fail"
                        summary = (
                            "SonarQube PR-scoped gate could not be evaluated: no new-code (new_*) gate conditions found. "
                            "Add new-code conditions to the Quality Gate or run with --sonar-gate-scope full."
                        )
                    elif gate.status != "OK":
                        status = "fail"
                        summary = f"SonarQube Quality Gate failed: {gate.status}"

        # Commit if all gates pass + requested + changes exist
        commit_msg = f"refactor({scope}): clean code compliance"
        committed = False
        semantic_report = None
        if status == "pass" and args.semantic and files:
            semantic_rules_path = Path(args.semantic_rules)
            if not semantic_rules_path.exists():
                status = "fail"
                summary = f"Semantic gate enabled but rules file not found: {semantic_rules_path}"
            else:
                semantic_out_dir = (
                    Path(args.semantic_out_dir)
                    if str(args.semantic_out_dir).strip()
                    else default_semantic_out_dir()
                )

                semantic_report = run_semantic_scaffold(
                    base_ref=args.base,
                    head_ref=args.head,
                    files=files,
                    rules_path=semantic_rules_path,
                    max_diff_chars=int(args.semantic_max_diff_chars),
                    out_dir=semantic_out_dir,
                )

                if not args.semantic_scaffold_only:
                    ledger_path = semantic_out_dir / "semantic_ledger.yml"
                    semantic_validation = load_and_validate_ledger(
                        ledger_path=ledger_path,
                        files=files,
                        rules_path=semantic_rules_path,
                    )
                    semantic_report = {**semantic_report, **semantic_validation}

                    sem_summary = semantic_validation.get("summary", {})
                    sem_fails = int(sem_summary.get("fails", 0) or 0)
                    sem_needs = int(sem_summary.get("needs_human", 0) or 0)
                    sem_status = str(semantic_validation.get("status", "")).strip()

                    if sem_status != "pass":
                        status = "fail"
                        if sem_status == "pending":
                            summary = (
                                "Semantic ledger pending evaluation. "
                                f"Review '{ledger_path}' using the prompt at '{semantic_out_dir / 'semantic_prompt.md'}', "
                                "set PASS/FAIL/NA for each entry (NEEDS_HUMAN only if truly undecidable), then re-run."
                            )
                        elif sem_status == "requires_reviewer":
                            summary = (
                                f"Semantic gate requires reviewer input: fails={sem_fails}, needs_human={sem_needs} "
                                f"(ledger: {ledger_path})."
                            )
                        else:
                            summary = (
                                f"Semantic gate failed: fails={sem_fails}, needs_human={sem_needs} "
                                f"(ledger: {ledger_path})."
                            )

        if status == "pass" and args.commit and git_has_changes():
            ensure_clean_working_tree(allowed_dirty_paths=files, ignore_untracked=True)
            git_commit(commit_msg, paths=files)
            committed = True

        report: Dict = {
            "status": status,
            "changed_files": files,
            "fixed_files": sorted(set(fixed_files)),
            "violations": [asdict(v) for v in all_violations],
            "sonar": sonar_report,
            "semantic": semantic_report,
            "commit": {
                "attempted": args.commit,
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
