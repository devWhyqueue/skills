from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .props import discover_report_task, read_project_properties, resolve_path


_PYSONAR_BOOTSTRAP = (
    "import truststore; truststore.inject_into_ssl(); "
    "from pysonar_scanner.__main__ import main; main()"
)
"""Inline bootstrap that injects the OS trust-store (needed for self-signed
certs) and explicitly calls ``main()``.  Some pysonar versions omit the
``if __name__ == '__main__'`` guard, so ``-m pysonar_scanner`` silently
exits 0 without scanning."""

DEFAULT_SCAN_TIMEOUT_SECONDS = 1200
ANALYSIS_LOG_TAIL_LINES = 20


def _venv_tool_cmd(tool: str) -> List[str]:
    """
    Resolve a console script from this skill's `.venv`.

    This skill is meant to be run with `...\\.venv\\Scripts\\python.exe` without
    relying on PATH or external fallbacks.
    """
    if tool == "pysonar":
        return [sys.executable, "-c", _PYSONAR_BOOTSTRAP]

    exe_suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).with_name(f"{tool}{exe_suffix}")
    if sibling.exists():
        return [str(sibling)]

    raise RuntimeError(
        f"Missing required tool '{tool}{exe_suffix}' next to interpreter: {Path(sys.executable)}"
    )


def _scan_timeout_seconds() -> int:
    raw_value = (os.getenv("SONAR_SCAN_TIMEOUT_SEC") or "").strip()
    if not raw_value:
        return DEFAULT_SCAN_TIMEOUT_SECONDS
    try:
        timeout = int(raw_value)
    except ValueError:
        return DEFAULT_SCAN_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_SCAN_TIMEOUT_SECONDS


def _analysis_log_tail(
    *,
    scanner_working_directory: Optional[Path],
    props: dict[str, str],
) -> str:
    base_dir = Path.cwd()
    project_base = props.get("sonar.projectBaseDir")
    if project_base:
        base_dir = resolve_path(project_base, base_dir=base_dir)

    candidates: list[Path] = []
    if scanner_working_directory is not None:
        candidates.append(scanner_working_directory / "scanner-report" / "analysis.log")

    workdir_value = props.get("sonar.working.directory")
    if workdir_value:
        candidates.append(
            resolve_path(workdir_value, base_dir=base_dir) / "scanner-report" / "analysis.log"
        )

    if scanner_working_directory is None and workdir_value is None:
        candidates.append(base_dir / ".sonar" / "scanner-report" / "analysis.log")
        candidates.append(base_dir / ".scannerwork" / "scanner-report" / "analysis.log")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        tail = "\n".join(lines[-ANALYSIS_LOG_TAIL_LINES:])
        if tail:
            return f"Last lines from {candidate}:\n{tail}"
    return ""


def run_scan(
    token: str,
    branch: str,
    reference_branch: Optional[str] = None,
    project_base_dir: Optional[Path] = None,
    scanner_metadata_path: Optional[Path] = None,
    scanner_working_directory: Optional[Path] = None,
    pull_request_key: Optional[str] = None,
    pull_request_branch: Optional[str] = None,
    pull_request_base: Optional[str] = None,
    host_url: Optional[str] = None,
    project_key: Optional[str] = None,
    sources: Optional[str] = None,
    inclusions: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> subprocess.CompletedProcess[str]:
    extra_args = extra_args or []

    env = os.environ.copy()
    # The skill waits for the CE task itself after the scan. Leaving
    # scanner-side quality-gate waiting enabled can block pysonar indefinitely.
    env["SONAR_QUALITYGATE_WAIT"] = "false"
    # WSL-mounted repos can confuse SCM-based exclusions and leave pysonar
    # preprocessing in a zero-file loop. The skill already narrows scope with
    # explicit sources and inclusions, so SCM exclusions are unnecessary here.
    env["SONAR_SCM_EXCLUSIONS_DISABLED"] = "true"
    env["SONAR_SCM_DISABLED"] = "true"
    # Python analyzer parallelism can stall on some mounted filesystems.
    env["SONAR_PYTHON_ANALYSIS_PARALLEL"] = "false"
    skill_root = str(Path(__file__).resolve().parent.parent)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        skill_root
        if not existing_pythonpath
        else f"{skill_root}{os.pathsep}{existing_pythonpath}"
    )

    props = read_project_properties()

    cmd = _venv_tool_cmd("pysonar") + ["-t", token]
    if pull_request_key:
        cmd.append(f"-Dsonar.pullrequest.key={pull_request_key}")
        cmd.append(f"-Dsonar.pullrequest.branch={pull_request_branch or branch}")
        cmd.append(
            f"-Dsonar.pullrequest.base={pull_request_base or reference_branch or 'develop'}"
        )
    else:
        cmd += ["--sonar-branch-name", branch]

    if host_url:
        cmd.extend(["--sonar-host-url", host_url])
    if project_key:
        cmd.extend(["--sonar-project-key", project_key])
    if project_base_dir is not None:
        cmd.extend(["--sonar-project-base-dir", str(project_base_dir)])
    if sources:
        cmd.extend(["--sonar-sources", sources])
    if inclusions and inclusions != sources and "sonar.inclusions" not in props:
        cmd.append(f"-Dsonar.inclusions={inclusions}")

    if "sonar.sourceEncoding" not in props:
        cmd.append("-Dsonar.sourceEncoding=UTF-8")
    scm_disabled = props.get("sonar.scm.disabled", "").strip().lower() == "true"
    if "sonar.scm.disabled" not in props:
        cmd.append("-Dsonar.scm.disabled=true")
    elif not scm_disabled and "sonar.scm.provider" not in props:
        cmd.append("-Dsonar.scm.provider=git")
    if "sonar.exclusions" not in props:
        cmd.append(
            "-Dsonar.exclusions=**/.venv/**,**/venv/**,**/.mypy_cache/**,**/.ruff_cache/**,**/__pycache__/**,**/dist/**,**/build/**,**/.git/**"
        )

    if reference_branch and "sonar.newCode.referenceBranch" not in props:
        cmd.append(f"-Dsonar.newCode.referenceBranch={reference_branch}")

    if scanner_working_directory and "sonar.working.directory" not in props:
        cmd.append(f"-Dsonar.working.directory={scanner_working_directory}")

    if scanner_metadata_path and "sonar.scanner.metadataFilePath" not in props:
        cmd.append(f"-Dsonar.scanner.metadataFilePath={scanner_metadata_path}")

    cmd += extra_args

    timeout_seconds = _scan_timeout_seconds()
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log_tail = _analysis_log_tail(
            scanner_working_directory=scanner_working_directory,
            props=props,
        )
        details = f"pysonar timed out after {timeout_seconds}s."
        if log_tail:
            details = f"{details}\n{log_tail}"
        raise RuntimeError(details) from exc
    code, out, err = p.returncode, p.stdout, p.stderr
    if code != 0:
        try:
            base_dir = Path.cwd()
            project_base = props.get("sonar.projectBaseDir")
            if project_base:
                base_dir = resolve_path(project_base, base_dir=base_dir)
            report, _ = discover_report_task(
                base_dir=base_dir,
                props=props,
                scanner_metadata_path=scanner_metadata_path,
                scanner_working_directory=scanner_working_directory,
                temp_dir=None,
            )
            if report is None:
                raise RuntimeError("Missing report-task.txt (pysonar output).")
        except Exception as e:
            log_tail = _analysis_log_tail(
                scanner_working_directory=scanner_working_directory,
                props=props,
            )
            extra = f"\n{log_tail}" if log_tail else ""
            raise RuntimeError(
                f"pysonar failed (exit {code}).\nSTDOUT:\n{out}\nSTDERR:\n{err}{extra}"
            ) from e
    return p
