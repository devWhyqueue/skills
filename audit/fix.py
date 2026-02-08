from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class FixResult:
    file: str
    changed: bool
    actions: List[str]


def run(cmd: List[str], env: dict | None = None) -> Tuple[int, str, str]:
    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    return p.returncode, p.stdout, p.stderr


def tool_cmd(tool: str) -> List[str]:
    """Resolve a console script from this skill's `.venv` (no PATH fallbacks)."""
    exe_suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).with_name(f"{tool}{exe_suffix}")
    if sibling.exists():
        return [str(sibling)]
    raise RuntimeError(
        f"Missing required tool '{tool}{exe_suffix}' next to interpreter: {Path(sys.executable)}"
    )


def has_ruff() -> bool:
    code, _, _ = run(tool_cmd("ruff") + ["--version"])
    return code == 0


def ensure_logger_scaffold(source: str) -> str:
    """
    If the file contains print(), we try a safe transformation:
    - add `import logging` if missing
    - add `logger = logging.getLogger(__name__)` if missing
    """
    if "print(" not in source:
        return source

    lines = source.splitlines()
    has_logging_import = any(
        re.match(r"^\s*import\s+logging\s*$", line) for line in lines
    ) or any(re.match(r"^\s*from\s+logging\s+import\s+", line) for line in lines)
    has_logger = any(
        re.match(r"^\s*logger\s*=\s*logging\.getLogger\(__name__\)\s*$", line)
        for line in lines
    )

    if not has_logging_import:
        insert_at = 0
        if lines and (lines[0].startswith('"""') or lines[0].startswith("'''")):
            for j in range(1, len(lines)):
                if lines[j].endswith('"""') or lines[j].endswith("'''"):
                    insert_at = j + 1
                    break

        for i, line in enumerate(lines):
            if re.match(r"^\s*(import|from)\s+", line):
                insert_at = i
                break

        lines.insert(insert_at, "import logging")

    if not has_logger:
        last_import_idx = -1
        for i, line in enumerate(lines):
            if re.match(r"^\s*(import|from)\s+", line):
                last_import_idx = i
        if last_import_idx >= 0:
            lines.insert(last_import_idx + 1, "")
            lines.insert(last_import_idx + 2, "logger = logging.getLogger(__name__)")

    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def replace_print_with_logger(source: str) -> str:
    """
    Best-effort replacement for simple prints:
      print("x") -> logger.info("x")
    Complex patterns remain unchanged for semantic refactor.
    """
    out_lines = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            out_lines.append(line)
            continue

        m = re.match(r"^(\s*)print\((.*)\)\s*$", line)
        if m:
            indent, inner = m.group(1), m.group(2).strip()
            out_lines.append(f"{indent}logger.info({inner})")
        else:
            out_lines.append(line)

    return "\n".join(out_lines) + ("\n" if source.endswith("\n") else "")


def ruff_fix_and_format(files: List[str]) -> None:
    """
    Ruff is our main mechanical enforcer:
    - fixes unused imports, trivial style issues
    - formats consistently
    """
    if not files or not has_ruff():
        return

    ruff = tool_cmd("ruff")
    env = os.environ.copy()
    env["RUFF_CACHE_DIR"] = str(
        Path(tempfile.gettempdir()) / "clean-code" / "ruff-cache"
    )

    run(ruff + ["check", "--fix", *files], env=env)
    run(ruff + ["format", *files], env=env)


def fix_files(files: List[str]) -> List[FixResult]:
    results: List[FixResult] = []

    for f in files:
        path = Path(f)
        if not path.exists():
            continue

        before = path.read_text(encoding="utf-8", errors="replace")

        after = ensure_logger_scaffold(before)
        after2 = replace_print_with_logger(after)

        changed = after2 != before
        actions: List[str] = []
        if after != before:
            actions.append("add_logging_scaffold")
        if after2 != after:
            actions.append("replace_print_with_logger")

        if changed:
            path.write_text(after2, encoding="utf-8")

        results.append(FixResult(file=f, changed=changed, actions=actions))

    ruff_fix_and_format([r.file for r in results])

    return results
