"""Format concise and JSON runner output."""

from __future__ import annotations

import json
from typing import Any

MAX_FINDINGS = 20
MAX_PYTEST_LINES = 30
MAX_LINE_LENGTH = 300


def format_report(report: dict[str, Any], *, as_json: bool) -> str:
    """Return either the full JSON report or its concise text representation."""
    if as_json:
        return json.dumps(report, separators=(",", ":"))
    return "\n".join(_report_lines(report))


def _report_lines(report: dict[str, Any]) -> list[str]:
    status = str(report.get("status", "fail")).upper()
    scope = report.get("scope") or "all"
    mode = report.get("pipeline_mode") or "default"
    files = len(_items(report.get("changed_files")))
    fixed = len(_items(report.get("fixed_files")))
    stage = _failed_stage(report)
    header = f"{status} clean-code | scope={scope} | mode={mode} | files={files} | fixed={fixed}"
    if stage:
        header += f" | stage={stage}"
    lines = [header, str(report.get("summary", ""))]
    lines.extend(_stage_lines(report, stage))
    next_action = report.get("next_action")
    if next_action:
        lines.append(f"Next: {next_action}")
    return [line for line in lines if line]


def _items(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _failed_stage(report: dict[str, Any]) -> str | None:
    if _items(report.get("violations")):
        return "audit"
    for stage in ("vulture", "pyright", "pytest", "sonar", "semantic"):
        value = report.get(stage)
        if isinstance(value, dict) and _stage_failed(stage, value):
            return stage
    return None


def _stage_failed(stage: str, value: dict[str, Any]) -> bool:
    if stage == "vulture":
        return bool(_items(value.get("issues"))) or int(
            value.get("exit_code", 0)
        ) not in {0, 3}
    if stage == "pyright":
        return bool(_items(value.get("issues"))) or int(value.get("exit_code", 0)) != 0
    if stage == "pytest":
        return int(value.get("exit_code", 0)) not in {0, 5}
    if stage == "sonar":
        return value.get("quality_gate") not in {None, "OK"}
    return value.get("status") not in {None, "pass"}


def _stage_lines(report: dict[str, Any], failed_stage: str | None) -> list[str]:
    if failed_stage == "audit":
        return _finding_lines(_items(report.get("violations")))
    stage_report = report.get(failed_stage) if failed_stage else None
    if not isinstance(stage_report, dict):
        return _passing_stage_lines(report)
    if failed_stage == "pytest":
        return _pytest_lines(stage_report)
    if failed_stage == "semantic":
        return _semantic_lines(stage_report)
    issues = _items(stage_report.get("issues") or stage_report.get("new_issues"))
    return _finding_lines(issues) or [f"{failed_stage}: {stage_report}"]


def _passing_stage_lines(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for stage in ("vulture", "pyright", "pytest", "sonar", "semantic"):
        value = report.get(stage)
        if not isinstance(value, dict):
            continue
        duration = value.get("duration_sec")
        suffix = f", {duration}s" if isinstance(duration, (int, float)) else ""
        lines.append(f"{stage}: pass{suffix}")
    return lines


def _finding_lines(findings: list[Any]) -> list[str]:
    lines = [
        _format_finding(item)
        for item in findings[:MAX_FINDINGS]
        if isinstance(item, dict)
    ]
    omitted = len(findings) - MAX_FINDINGS
    if omitted > 0:
        lines.append(f"… {omitted} additional findings; use --json for all details.")
    return lines


def _format_finding(finding: dict[str, Any]) -> str:
    file = finding.get("file") or finding.get("component") or "<unknown>"
    line = finding.get("line")
    location = f"{file}:{line}" if line else str(file)
    label = finding.get("rule") or finding.get("rule_id") or finding.get("severity")
    message = str(finding.get("message", ""))
    prefix = f" [{label}]" if label else ""
    return _truncate(f"{location}{prefix} {message}".rstrip())


def _pytest_lines(report: dict[str, Any]) -> list[str]:
    output = str(report.get("stdout", ""))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    tail = [_truncate(line) for line in lines[-MAX_PYTEST_LINES:]]
    if len(lines) > MAX_PYTEST_LINES:
        tail.insert(0, "… earlier pytest output omitted; use --json for all details.")
    return tail or [str(report.get("summary", "Pytest failed."))]


def _semantic_lines(report: dict[str, Any]) -> list[str]:
    lines = [str(report.get("status", "semantic review required"))]
    for key in ("ledger_path", "prompt_path"):
        if value := report.get(key):
            lines.append(f"{key}: {value}")
    return lines


def _truncate(value: str) -> str:
    """Limit a displayed diagnostic line while retaining an omission marker."""
    return (
        value if len(value) <= MAX_LINE_LENGTH else value[: MAX_LINE_LENGTH - 1] + "…"
    )
