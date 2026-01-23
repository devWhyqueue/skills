from __future__ import annotations

import ast
import re
from collections.abc import Iterable


def iter_public_functions(tree: ast.AST) -> Iterable[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            yield node


def has_docstring(func: ast.FunctionDef) -> bool:
    return ast.get_docstring(func) is not None


def all_args_typed(func: ast.FunctionDef) -> bool:
    def is_any_or_missing(ann: ast.AST | None) -> bool:
        if ann is None:
            return True
        if isinstance(ann, ast.Name) and ann.id == "Any":
            return True
        if isinstance(ann, ast.Attribute) and ann.attr == "Any":
            return True
        return False

    for arg in func.args.args:
        if arg.arg in {"self", "cls"}:
            continue
        if is_any_or_missing(arg.annotation):
            return False

    if is_any_or_missing(func.returns):
        return False

    return True


def function_length_lines(func: ast.FunctionDef) -> int:
    start = getattr(func, "lineno", None)
    end = getattr(func, "end_lineno", None)
    if start is None or end is None:
        return 0
    start = max(int(start), 1)
    end = max(int(end), start)
    return (end - start) + 1


def is_airflow_length_exempt(func: ast.FunctionDef) -> bool:
    """
    Return True if this function is an Airflow DAG/task_group factory.

    Supported patterns:
    - @dag / @dag(...)
    - @task_group / @task_group(...)
    - @something.dag / @something.dag(...)
    - @something.task_group / @something.task_group(...)
    """

    def is_decorator(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in {"dag", "task_group"}
        if isinstance(node, ast.Attribute):
            return node.attr in {"dag", "task_group"}
        if isinstance(node, ast.Call):
            return is_decorator(node.func)
        return False

    return any(is_decorator(dec) for dec in func.decorator_list)


def detect_imports_not_at_file_top(source: str, tree: ast.AST) -> list[tuple[int, str]]:
    """
    Detect imports that appear after non-import statements at module top-level.

    Allowed prelude:
    - module docstring
    - __future__ imports
    - regular imports
    Everything else ends the "import block"; any later import is a violation.
    """
    if not isinstance(tree, ast.Module):
        return []

    def is_module_docstring(stmt: ast.stmt) -> bool:
        if not isinstance(stmt, ast.Expr):
            return False
        val = getattr(stmt, "value", None)
        return isinstance(val, ast.Constant) and isinstance(val.value, str)

    def is_future_import(stmt: ast.stmt) -> bool:
        return isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"

    def line_evidence(line_no: int) -> str:
        lines = source.splitlines()
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
        return ""

    hits: list[tuple[int, str]] = []
    in_import_block = True

    for stmt in tree.body:
        if in_import_block:
            if is_module_docstring(stmt) or is_future_import(stmt):
                continue
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            in_import_block = False

        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            line_no = getattr(stmt, "lineno", None)
            if line_no is not None:
                hits.append((int(line_no), line_evidence(int(line_no))))

    return hits


_SNAKE_CASE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_CONSTANT_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def detect_non_snake_case_identifiers(tree: ast.AST) -> list[tuple[int, str]]:
    """
    Best-effort checks for identifiers that violate the `snake_case` rule.

    Scope (intentionally limited to avoid excessive false positives):
    - function names
    - function parameter names (incl. *args/**kwargs)
    - module-level assignment targets

    Notes:
    - allows ALL_CAPS names for module-level constants
    - ignores self/cls
    """

    def is_snake(name: str) -> bool:
        return bool(_SNAKE_CASE_RE.match(name))

    def is_constant(name: str) -> bool:
        return bool(_CONSTANT_RE.match(name))

    hits: set[tuple[int, str]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not (node.name.startswith("__") and node.name.endswith("__")):
                if not is_snake(node.name):
                    hits.add(
                        (getattr(node, "lineno", None) or 1, f"def {node.name}(...)")
                    )

            args = node.args
            all_params: list[ast.arg] = (
                list(getattr(args, "posonlyargs", []))
                + list(args.args)
                + list(args.kwonlyargs)
            )
            if args.vararg is not None:
                all_params.append(args.vararg)
            if args.kwarg is not None:
                all_params.append(args.kwarg)

            for a in all_params:
                if a.arg in {"self", "cls"}:
                    continue
                if not is_snake(a.arg):
                    hits.add(
                        (
                            getattr(a, "lineno", None)
                            or getattr(node, "lineno", None)
                            or 1,
                            f"parameter '{a.arg}'",
                        )
                    )

    if isinstance(tree, ast.Module):
        for stmt in tree.body:
            targets: list[ast.expr] = []
            if isinstance(stmt, ast.Assign):
                targets = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]

            for t in targets:
                if isinstance(t, ast.Name):
                    if not (is_snake(t.id) or is_constant(t.id)):
                        hits.add(
                            (
                                getattr(t, "lineno", None)
                                or getattr(stmt, "lineno", None)
                                or 1,
                                f"assignment target '{t.id}'",
                            )
                        )

    return sorted(hits, key=lambda x: (x[0], x[1]))
