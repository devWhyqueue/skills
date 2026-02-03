from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from audit.fix import run, tool_cmd


def _build_vulture_cmd(paths: List[str]) -> List[str]:
    unique_paths = sorted({str(path) for path in paths})
    cmd: List[str] = [*tool_cmd("vulture")]
    config = Path("pyproject.toml")
    if config.exists():
        cmd.extend(["--config", str(config)])
    cmd.extend(unique_paths)
    return cmd


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
    *, enabled: bool, changed_files: List[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """Run Vulture on changed files and return a structured report.

    Args:
        enabled: Whether the Vulture gate is enabled.
        changed_files: List of changed Python files to analyze.

    Returns:
        A tuple of (report, summary, failed).
    """
    if not enabled:
        return None, None, False
    if not changed_files:
        report: Dict[str, Any] = {"tool": "vulture", "exit_code": 0, "issues": []}
        return report, None, False
    cmd = _build_vulture_cmd(changed_files)
    code, output, _ = run(cmd)
    issues = _parse_vulture_output(output)
    report = {"tool": "vulture", "exit_code": code, "issues": issues}
    if code in (1, 2):
        return report, "Vulture failed (invalid input or arguments).", True
    if issues:
        return report, "Vulture detected dead code in changed files.", True
    if code not in (0, 3):
        return report, "Vulture exited with an unexpected status.", True
    return report, None, False
