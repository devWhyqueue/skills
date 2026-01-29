from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from audit.fix import run, tool_cmd

DEFAULT_PYRIGHT_LEVEL = "warning"
_PYRIGHT_LEVELS = {"error", "warning"}


def _resolve_pyright_config(path: str) -> Optional[Path]:
    if not path:
        return None
    candidate = Path(path)
    if candidate.exists():
        return candidate
    return None


def run_pyright_gate(
    *,
    enabled: bool,
    package_dir: Optional[Path],
) -> tuple[Optional[dict[str, object]], Optional[str], bool]:
    if not enabled:
        return None, None, False

    config_path = _resolve_pyright_config(os.getenv("PYRIGHT_CONFIG") or "")
    level = (os.getenv("PYRIGHT_LEVEL") or DEFAULT_PYRIGHT_LEVEL).strip() or DEFAULT_PYRIGHT_LEVEL
    if level not in _PYRIGHT_LEVELS:
        level = DEFAULT_PYRIGHT_LEVEL

    cmd = tool_cmd("pyright")
    cmd.append("--outputjson")
    if config_path is not None:
        cmd += ["--project", str(config_path)]
    else:
        cmd += ["--level", level]

    if package_dir is not None:
        cmd.append(str(package_dir))

    code, out, err = run(cmd)
    issues = _parse_pyright_issues(out)
    report = {
        "tool": "pyright",
        "command": cmd,
        "exit_code": code,
        "stdout": out,
        "stderr": err,
        "config": (config_path.as_posix() if config_path is not None else None),
        "level": level if config_path is None else None,
        "package": (package_dir.as_posix() if package_dir is not None else None),
        "issues": issues,
    }

    if code != 0:
        return report, "Pyright type check failed.", True

    return report, None, False


def _parse_pyright_issues(output: str) -> list[dict[str, object]]:
    if not output.strip():
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []

    diagnostics = payload.get("generalDiagnostics", [])
    issues: list[dict[str, object]] = []
    for diag in diagnostics:
        file_path = diag.get("file") or diag.get("uri")
        range_info = diag.get("range") or {}
        start = range_info.get("start") or {}
        line = start.get("line")
        issues.append(
            {
                "file": file_path,
                "line": (int(line) + 1) if isinstance(line, int) else None,
                "severity": diag.get("severity"),
                "rule": diag.get("rule"),
                "message": diag.get("message"),
            }
        )
    return issues
