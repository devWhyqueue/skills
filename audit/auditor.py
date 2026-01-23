from __future__ import annotations

import ast
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
from .checks_text import (
    detect_broad_except,
    detect_commented_out_code,
    detect_local_imports,
    detect_mixed_spark_sql_and_pyspark_api,
    detect_print_statements,
)
from .files import count_lines, filter_python_files, is_within_dir, read_text
from git import changed_files
from .models import Violation


def _package_root_for_file(path: Path) -> Path | None:
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def _count_python_files_in_package(pkg_dir: Path) -> int:
    return sum(1 for p in pkg_dir.iterdir() if p.is_file() and p.suffix == ".py")


def audit_file(path: str | Path) -> list[Violation]:
    path_str = str(path)
    source = read_text(path)
    violations: list[Violation] = []

    loc = count_lines(source)
    if loc > 250:
        violations.append(
            Violation(
                rule_id="structure.file_max_loc",
                file=path_str,
                line=None,
                message=f"File exceeds 250 lines ({loc}).",
            )
        )

    if detect_mixed_spark_sql_and_pyspark_api(source):
        violations.append(
            Violation(
                rule_id="structure.no_mixed_spark_styles",
                file=path_str,
                line=None,
                message="File appears to mix Spark SQL (spark.sql) and PySpark DataFrame API.",
            )
        )

    for line_no, evidence in detect_print_statements(source):
        violations.append(
            Violation(
                rule_id="organization.no_print",
                file=path_str,
                line=line_no,
                message="print() is prohibited; use logging.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_broad_except(source):
        violations.append(
            Violation(
                rule_id="quality.no_broad_exception",
                file=path_str,
                line=line_no,
                message="Avoid broad except Exception/BaseException; catch specific exceptions.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_commented_out_code(source):
        violations.append(
            Violation(
                rule_id="organization.no_commented_code",
                file=path_str,
                line=line_no,
                message="Commented-out code blocks are not allowed.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_local_imports(source):
        violations.append(
            Violation(
                rule_id="organization.imports_top_level_only",
                file=path_str,
                line=line_no,
                message="Imports must be top-level only (no local imports).",
                evidence=evidence,
            )
        )

    try:
        tree = ast.parse(source)

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
                    message="Identifiers must use snake_case (ALL_CAPS allowed for module constants).",
                    evidence=evidence,
                )
            )

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
    except SyntaxError as e:
        violations.append(
            Violation(
                rule_id="syntax.parse_error",
                file=path_str,
                line=e.lineno,
                message=f"Syntax error prevents analysis: {e.msg}",
            )
        )

    pkg_root = _package_root_for_file(Path(path_str))
    if pkg_root is not None:
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


def audit_changed_python_files(
    base_ref: str, head_ref: str, *, package_dir: Path | None = None
) -> tuple[list[str], list[Violation]]:
    files = filter_python_files(changed_files(base_ref, head_ref))
    if package_dir is not None:
        files = [f for f in files if is_within_dir(Path(f), package_dir)]

    violations: list[Violation] = []
    for f in files:
        violations.extend(audit_file(f))
    return files, violations
