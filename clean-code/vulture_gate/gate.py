from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from audit.fix import run, tool_cmd


# Glob patterns to exclude dirs whose name starts with a dot (e.g. .venv, .git).
# Used when scanning from "." so Vulture does not recurse into them.
_EXCLUDE_DOT_DIRS = (".*", "*/.?*")

# Exclude paths under directories named 'test' or 'tests' so we never analyse test code.
_EXCLUDE_TEST_DIRS = ("test/*", "tests/*", "*/test/*", "*/tests/*")


def _default_scan_paths() -> List[str]:
    """Default paths for Vulture: src/ if present (avoids .venv etc.), else ."""
    src = Path("src")
    if src.exists() and src.is_dir():
        return [src.as_posix()]
    return ["."]


def _build_vulture_cmd(scan_paths: List[str]) -> List[str]:
    cmd: List[str] = [*tool_cmd("vulture")]
    config = Path("pyproject.toml")
    if config.exists():
        cmd.extend(["--config", str(config)])
    # When scanning "." avoid recursing into dot-prefixed dirs (.venv, .git, etc.)
    if "." in scan_paths:
        for pattern in _EXCLUDE_DOT_DIRS:
            cmd.extend(["--exclude", pattern])
    # Never analyse test code (any path under test/ or tests/).
    for pattern in _EXCLUDE_TEST_DIRS:
        cmd.extend(["--exclude", pattern])
    cmd.extend(scan_paths)
    return cmd


def _normalize_path(path: str) -> str:
    return Path(path).as_posix()


def _is_under_path(normalized_file: str, package_dir: Path) -> bool:
    """True if normalized_file is under package_dir (or equal)."""
    scope_norm = _normalize_path(package_dir.as_posix())
    return normalized_file == scope_norm or normalized_file.startswith(scope_norm + "/")


def _filter_issues_to_changed(
    issues: List[Dict[str, Any]],
    changed_files: List[str],
    package_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Keep only issues in changed files and, if scope set, within package_dir."""
    changed_set: Set[str] = {_normalize_path(f) for f in changed_files}
    result: List[Dict[str, Any]] = []
    for i in issues:
        norm = _normalize_path(i["file"])
        if norm not in changed_set:
            continue
        if package_dir is not None and not _is_under_path(norm, package_dir):
            continue
        result.append(i)
    return result


def _parse_vulture_issue_line(line: str) -> Optional[Dict[str, Any]]:
    text = line.strip()
    if not text or "confidence" not in text:
        return None
    parts = text.split(":", 2)
    if len(parts) != 3:
        return None
    file_path = parts[0].strip()
    line_text = parts[1].strip()
    message_part = parts[2].strip()
    match = re.search(r"\(\d+% confidence\)\s*$", message_part)
    message = message_part[: match.start()].rstrip() if match else message_part
    name = ""
    kind = ""
    usage_match = re.search(r"unused\s+([a-zA-Z_]+)\s+'([^']+)'", message)
    if usage_match:
        kind = usage_match.group(1)
        name = usage_match.group(2)
    line_number = int(line_text) if line_text.isdigit() else None
    issue: Dict[str, Any] = {
        "file": file_path,
        "line": line_number,
        "name": name,
        "type": kind,
        "message": message,
    }
    return issue


def _parse_vulture_output(output: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for raw_line in output.splitlines():
        issue = _parse_vulture_issue_line(raw_line)
        if issue is not None:
            issues.append(issue)
    return issues


def run_vulture_gate(
    *,
    enabled: bool,
    changed_files: List[str],
    package_dir: Optional[Path] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """Run Vulture on the full project (default src/), then report only issues in changed files (and scope).

    Vulture is run on src/ if present (to avoid .venv and other large dirs), else
    on . so it sees cross-file usage. Reported issues are filtered to: (1) file
    must be in changed_files, and (2) if package_dir is set, file must be under
    that scope.

    Args:
        enabled: Whether the Vulture gate is enabled.
        changed_files: List of changed Python files; only issues in these files fail.
        package_dir: If set, only issues in files under this path are reported.

    Returns:
        A tuple of (report, summary, failed).
    """
    if not enabled:
        return None, None, False
    if not changed_files:
        report: Dict[str, Any] = {"tool": "vulture", "exit_code": 0, "issues": []}
        return report, None, False
    cmd = _build_vulture_cmd(_default_scan_paths())
    code, output, _ = run(cmd)
    all_issues = _parse_vulture_output(output)
    issues = _filter_issues_to_changed(all_issues, changed_files, package_dir)
    report = {"tool": "vulture", "exit_code": code, "issues": issues}
    if code in (1, 2):
        return report, "Vulture failed (invalid input or arguments).", True
    if issues:
        return report, "Vulture detected dead code in changed files.", True
    if code not in (0, 3):
        return report, "Vulture exited with an unexpected status.", True
    return report, None, False
