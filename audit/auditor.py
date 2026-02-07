from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

from .checks_ast import (
    all_args_typed,
    detect_imports_not_at_file_top,
    detect_non_snake_case_identifiers,
    function_length_lines,
    has_docstring,
    is_airflow_length_exempt,
    iter_public_functions,
)
from .checks_text import collect_text_violation_tuples
from .files import filter_python_files, is_within_dir, read_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Violation:
    """A single clean-code rule violation."""

    rule_id: str
    file: str
    line: int | None
    message: str
    evidence: str | None = None


def _package_root_for_file(path: Path) -> Path | None:
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def _count_python_files_in_package(pkg_dir: Path) -> int:
    return sum(1 for p in pkg_dir.iterdir() if p.is_file() and p.suffix == ".py")


def _collect_text_violations(path_str: str, source: str) -> list[Violation]:
    """Collect violations from text-based checks (no AST)."""
    return [
        Violation(rule_id=rid, file=path_str, line=ln, message=msg, evidence=ev)
        for rid, ln, msg, ev in collect_text_violation_tuples(path_str, source)
    ]


def _collect_ast_violations_imports_and_naming(
    path_str: str, source: str, tree: ast.AST
) -> list[Violation]:
    """AST checks: imports at top, snake_case."""
    violations: list[Violation] = []
    for line_no, evidence in detect_imports_not_at_file_top(source, tree):
        violations.append(
            Violation(
                rule_id="organization.imports_at_file_top",
                file=path_str,
                line=line_no,
                message="Imports must be placed at the top of the file (after module docstring/__future__ imports).",
                evidence=evidence,
            )
        )
    for line_no, evidence in detect_non_snake_case_identifiers(tree):
        violations.append(
            Violation(
                rule_id="naming.snake_case",
                file=path_str,
                line=line_no,
                message="Identifiers must use snake_case (ALL_CAPS for constants; PascalCase for type aliases).",
                evidence=evidence,
            )
        )
    return violations


def _collect_ast_violations_functions(path_str: str, tree: ast.AST) -> list[Violation]:
    """AST checks: docstring, type hints, function length."""
    violations: list[Violation] = []
    for func in iter_public_functions(tree):
        if not has_docstring(func):
            violations.append(
                Violation(
                    rule_id="quality.public_docstring_required",
                    file=path_str,
                    line=getattr(func, "lineno", None),
                    message=f"Public function '{func.name}' must have a docstring.",
                )
            )
        if not all_args_typed(func):
            violations.append(
                Violation(
                    rule_id="quality.public_type_hints_required",
                    file=path_str,
                    line=getattr(func, "lineno", None),
                    message=f"Public function '{func.name}' must have type hints (no Any, return required).",
                )
            )
        if not is_airflow_length_exempt(func):
            flen = function_length_lines(func)
            if flen > 25:
                violations.append(
                    Violation(
                        rule_id="organization.function_length",
                        file=path_str,
                        line=getattr(func, "lineno", None),
                        message=f"Function '{func.name}' is {flen} lines; should be < 25.",
                    )
                )
    return violations


def _collect_ast_violations(
    path_str: str, source: str, tree: ast.AST
) -> list[Violation]:
    """Collect violations from AST-based checks."""
    out = _collect_ast_violations_imports_and_naming(path_str, source, tree)
    out.extend(_collect_ast_violations_functions(path_str, tree))
    return out


def _collect_package_violations(path_str: str) -> list[Violation]:
    """Collect package-level structure violations."""
    violations: list[Violation] = []
    pkg_root = _package_root_for_file(Path(path_str))
    if pkg_root is None:
        return violations
    count_files = _count_python_files_in_package(pkg_root)
    if count_files > 7:
        violations.append(
            Violation(
                rule_id="structure.max_files_per_package",
                file=path_str,
                line=None,
                message=f"Package '{pkg_root}' has {count_files} Python files; should be <= 7.",
            )
        )
    return violations


def audit_file(path: str | Path) -> list[Violation]:
    """Run all clean-code checks on one file and return violations."""
    path_str = str(path)
    source = read_text(path)
    violations = _collect_text_violations(path_str, source)

    try:
        tree = ast.parse(source)
        violations.extend(_collect_ast_violations(path_str, source, tree))
    except SyntaxError as e:
        violations.append(
            Violation(
                rule_id="syntax.parse_error",
                file=path_str,
                line=e.lineno,
                message=f"Syntax error prevents analysis: {e.msg}",
            )
        )

    violations.extend(_collect_package_violations(path_str))
    return violations


def audit_python_files(
    files: list[str], *, package_dir: Path | None = None
) -> tuple[list[str], list[Violation]]:
    """Audit the given Python files; optionally restrict to paths under package_dir.

    Returns:
        (filtered file list, list of violations).
    """
    files = filter_python_files(files)
    if package_dir is not None:
        files = [f for f in files if is_within_dir(Path(f), package_dir)]

    violations: list[Violation] = []
    for f in files:
        violations.extend(audit_file(f))
    return files, violations
