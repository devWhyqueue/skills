from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from audit.fix import run, tool_cmd

COVERAGE_REPORT_FILENAME = "coverage.xml"
PYTEST_EXIT_NO_TESTS_COLLECTED = 5


def _coverage_module_from_path(path: str) -> Optional[str]:
    """Map a changed file path to the importable module name used by pytest-cov."""
    if not path.endswith(".py"):
        return None

    path_obj = Path(path)
    parts = path_obj.parts
    if not parts or path_obj.name == "__init__.py":
        return None

    if "tests" in parts or "test" in parts:
        return None

    module_parts = list(path_obj.with_suffix("").parts)
    if module_parts and module_parts[0] == "src":
        module_parts = module_parts[1:]
    if not module_parts:
        return None
    return ".".join(module_parts)


def _cov_modules_from_changed_files(changed_files: List[str]) -> List[str]:
    """Return module names for changed .py files so coverage is restricted to those files only.
    Excludes __init__.py so empty package inits do not drag down the percentage.
    """
    if not changed_files:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for f in changed_files:
        mod = _coverage_module_from_path(f)
        if mod is None:
            continue
        if mod not in seen:
            seen.add(mod)
            out.append(mod)
    return sorted(out)


def _parse_coverage_pct(stdout: str) -> Optional[float]:
    """Extract total coverage percentage from pytest-cov stdout.
    Tries the TOTAL table line first, then fallback to 'Total coverage: xx%' (e.g. on failure).
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("TOTAL") and "%" in line:
            match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
    match = re.search(
        r"(?:Total\s+)?coverage:\s*(\d+(?:\.\d+)?)\s*%", stdout, re.IGNORECASE
    )
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _build_pytest_cmd(
    changed_files: List[str], coverage_fail_under: int
) -> Tuple[List[str], Optional[str]]:
    """Build pytest command and optional coverage report path.
    Coverage is restricted to changed .py files (one --cov module per file).
    When coverage_fail_under is 0, coverage is reported but no threshold is enforced.
    """
    cmd: List[str] = [*tool_cmd("pytest"), "-q", "--tb=short"]
    coverage_report_path: Optional[str] = None
    cov_modules = _cov_modules_from_changed_files(changed_files)
    if cov_modules:
        for m in cov_modules:
            cmd.extend(["--cov", m])
        cmd.extend(["--cov-report", "term"])
        cmd.extend(["--cov-report", f"xml:{COVERAGE_REPORT_FILENAME}"])
        if coverage_fail_under > 0:
            cmd.append(f"--cov-fail-under={coverage_fail_under}")
        coverage_report_path = str(Path.cwd() / COVERAGE_REPORT_FILENAME)
    return cmd, coverage_report_path


def _pytest_report_dict(
    code: int,
    out: str,
    err: str,
    coverage_pct: Optional[float],
    coverage_report_path: Optional[str],
) -> Dict[str, Any]:
    """Build report dict and set summary from run result."""
    report: Dict[str, Any] = {
        "tool": "pytest",
        "exit_code": code,
        "stdout": out,
        "stderr": err,
        "coverage_pct": coverage_pct,
        "coverage_report_path": coverage_report_path,
        "summary": f"All tests passed; coverage {coverage_pct}%."
        if coverage_pct is not None
        else "All tests passed.",
    }
    if code == PYTEST_EXIT_NO_TESTS_COLLECTED:
        report["summary"] = "No tests collected."
    elif code != 0:
        report["summary"] = "Tests failed or coverage below threshold."
    return report


def run_pytest_gate(
    *,
    enabled: bool,
    changed_files: List[str],
    package_dir: Optional[Path] = None,
    coverage_fail_under: int = 0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """Run pytest with coverage on changed modules; require passing tests.
    When coverage_fail_under > 0, also require that coverage meets the threshold."""
    if not enabled:
        return None, None, False
    cmd, coverage_report_path = _build_pytest_cmd(changed_files, coverage_fail_under)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path.cwd()), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    code, out, err = run(cmd, env=env)
    coverage_pct = _parse_coverage_pct(out)
    report = _pytest_report_dict(code, out, err, coverage_pct, coverage_report_path)
    if code == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return report, None, False
    if code != 0:
        return (
            report,
            "Pytest stage failed: tests failed or coverage below required.",
            True,
        )
    return report, None, False
