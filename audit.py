from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


@dataclass
class Violation:
    rule_id: str
    file: str
    line: Optional[int]
    message: str
    evidence: Optional[str] = None


def run(cmd: List[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")
    return p.stdout


def git_ref_exists(ref: str) -> bool:
    p = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return p.returncode == 0


def detect_base_ref(preferred: str = "develop") -> str:
    if git_ref_exists(preferred):
        return preferred
    if git_ref_exists(f"origin/{preferred}"):
        return f"origin/{preferred}"
    return preferred


def merge_base(base_ref: str, head_ref: str) -> str:
    return run(["git", "merge-base", base_ref, head_ref]).strip()


def changed_files(base_ref: str, head_ref: str) -> List[str]:
    base = merge_base(base_ref, head_ref)
    out = run(["git", "diff", "--name-only", f"{base}..{head_ref}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def filter_python_files(files: Iterable[str]) -> List[str]:
    return [f for f in files if f.endswith(".py") and Path(f).exists()]


def _posix(p: Path) -> str:
    return p.as_posix().rstrip("/")


def is_within_dir(path: Path, directory: Path) -> bool:
    d = _posix(directory)
    p = _posix(path)
    return p == d or p.startswith(d + "/")


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def count_loc(text: str) -> int:
    return len(text.splitlines())


def iter_public_functions(tree: ast.AST) -> Iterable[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            yield node


def has_docstring(func: ast.FunctionDef) -> bool:
    return ast.get_docstring(func) is not None


def all_args_typed(func: ast.FunctionDef) -> bool:
    def is_bad_any(ann: ast.AST | None) -> bool:
        if ann is None:
            return True
        if isinstance(ann, ast.Name) and ann.id == "Any":
            return True
        if isinstance(ann, ast.Attribute) and ann.attr == "Any":
            return True
        return False

    for arg in func.args.args:
        if arg.arg in ("self", "cls"):
            continue
        if is_bad_any(arg.annotation):
            return False

    if is_bad_any(func.returns):
        return False

    return True


def function_length_lines(func: ast.FunctionDef) -> int:
    if (
        getattr(func, "end_lineno", None) is None
        or getattr(func, "lineno", None) is None
    ):
        return 0
    start = max(func.lineno, 1)
    end = max(func.end_lineno, start)
    return (end - start) + 1


def is_airflow_dag_function(func: ast.FunctionDef) -> bool:
    """
    Return True if this function is an Airflow DAG factory (decorated with @dag).

    We keep this heuristic intentionally narrow to avoid silently masking real issues.
    Supported patterns:
    - @dag
    - @dag(...)
    - @something.dag
    - @something.dag(...)
    """

    def is_dag_decorator(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "dag"
        if isinstance(node, ast.Attribute):
            return node.attr == "dag"
        return False

    for dec in func.decorator_list:
        if is_dag_decorator(dec):
            return True
        if isinstance(dec, ast.Call) and is_dag_decorator(dec.func):
            return True

    return False


def is_airflow_task_group_function(func: ast.FunctionDef) -> bool:
    """
    Return True if this function is an Airflow task group factory (decorated with @task_group).

    We keep this heuristic intentionally narrow to avoid silently masking real issues.
    Supported patterns:
    - @task_group
    - @task_group(...)
    - @something.task_group
    - @something.task_group(...)
    """

    def is_task_group_decorator(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "task_group"
        if isinstance(node, ast.Attribute):
            return node.attr == "task_group"
        return False

    for dec in func.decorator_list:
        if is_task_group_decorator(dec):
            return True
        if isinstance(dec, ast.Call) and is_task_group_decorator(dec.func):
            return True

    return False


def detect_broad_except(source: str) -> List[Tuple[int, str]]:
    hits = []
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(r"^\s*except\s+(Exception|BaseException)\s*:", line):
            hits.append((i, line.strip()))
    return hits


def detect_print_statements(source: str) -> List[Tuple[int, str]]:
    hits = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"\bprint\s*\(", line):
            hits.append((i, line.strip()))
    return hits


def detect_commented_out_code(source: str) -> List[Tuple[int, str]]:
    hits = []
    for i, line in enumerate(source.splitlines(), start=1):
        s = line.lstrip()
        if not s.startswith("#"):
            continue
        if re.search(
            r"#\s*(def |class |import |from |if |for |while |try:|except |with )", s
        ):
            hits.append((i, line.strip()))
    return hits


def detect_local_imports(source: str) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s+(import|from)\s+\w+", line):
            hits.append((i, line.strip()))
    return hits


_SNAKE_CASE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_CONSTANT_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _line_evidence(source: str, line_no: int) -> str:
    lines = source.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def detect_imports_not_at_file_top(source: str, tree: ast.AST) -> List[Tuple[int, str]]:
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

    hits: List[Tuple[int, str]] = []
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
                hits.append((line_no, _line_evidence(source, line_no)))

    return hits


def detect_non_snake_case_identifiers(
    tree: ast.AST,
) -> List[Tuple[int, str]]:
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

    hits: List[Tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not (node.name.startswith("__") and node.name.endswith("__")):
                if not is_snake(node.name):
                    hits.append(
                        (
                            getattr(node, "lineno", None) or 1,
                            f"def {node.name}(...)",
                        )
                    )

            args = node.args
            all_params = (
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
                    hits.append(
                        (
                            getattr(a, "lineno", None) or getattr(node, "lineno", None) or 1,
                            f"parameter '{a.arg}'",
                        )
                    )

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            # module-level only
            if not isinstance(getattr(node, "parent", None), ast.Module):
                continue

            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]

            for t in targets:
                if isinstance(t, ast.Name):
                    if not (is_snake(t.id) or is_constant(t.id)):
                        hits.append(
                            (
                                getattr(t, "lineno", None) or getattr(node, "lineno", None) or 1,
                                f"assignment target '{t.id}'",
                            )
                        )

    # de-dup (same line/evidence may be hit multiple times depending on AST walk order)
    return sorted(set(hits), key=lambda x: (x[0], x[1]))


def detect_mixed_spark_sql_and_pyspark_api(source: str) -> bool:
    has_sql = bool(re.search(r"\bspark\s*\.\s*sql\s*\(", source))
    has_df_api = bool(
        re.search(
            r"\.\s*(select|where|filter|groupBy|join|withColumn|agg)\s*\(", source
        )
    )
    return has_sql and has_df_api


def package_root_for_file(path: Path) -> Optional[Path]:
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def count_python_files_in_package(pkg_dir: Path) -> int:
    py_files = [p for p in pkg_dir.iterdir() if p.is_file() and p.suffix == ".py"]
    return len(py_files)


def audit_file(path: str) -> List[Violation]:
    source = read_text(path)
    violations: List[Violation] = []

    loc = count_loc(source)
    if loc > 250:
        violations.append(
            Violation(
                rule_id="structure.file_max_loc",
                file=path,
                line=None,
                message=f"File exceeds 250 lines ({loc}).",
            )
        )

    if detect_mixed_spark_sql_and_pyspark_api(source):
        violations.append(
            Violation(
                rule_id="structure.no_mixed_spark_styles",
                file=path,
                line=None,
                message="File appears to mix Spark SQL (spark.sql) and PySpark DataFrame API.",
            )
        )

    for line_no, evidence in detect_print_statements(source):
        violations.append(
            Violation(
                rule_id="organization.no_print",
                file=path,
                line=line_no,
                message="print() is prohibited; use logging.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_broad_except(source):
        violations.append(
            Violation(
                rule_id="quality.no_broad_exception",
                file=path,
                line=line_no,
                message="Avoid broad except Exception/BaseException; catch specific exceptions.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_commented_out_code(source):
        violations.append(
            Violation(
                rule_id="organization.no_commented_code",
                file=path,
                line=line_no,
                message="Commented-out code blocks are not allowed.",
                evidence=evidence,
            )
        )

    for line_no, evidence in detect_local_imports(source):
        violations.append(
            Violation(
                rule_id="organization.imports_top_level_only",
                file=path,
                line=line_no,
                message="Imports must be top-level only (no local imports).",
                evidence=evidence,
            )
        )

    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                setattr(child, "parent", node)

        for line_no, evidence in detect_imports_not_at_file_top(source, tree):
            violations.append(
                Violation(
                    rule_id="organization.imports_at_file_top",
                    file=path,
                    line=line_no,
                    message="Imports must be placed at the top of the file (after module docstring/__future__ imports).",
                    evidence=evidence,
                )
            )

        for line_no, evidence in detect_non_snake_case_identifiers(tree):
            violations.append(
                Violation(
                    rule_id="naming.snake_case",
                    file=path,
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
                        file=path,
                        line=getattr(func, "lineno", None),
                        message=f"Public function '{func.name}' must have a docstring.",
                    )
                )

            if not all_args_typed(func):
                violations.append(
                    Violation(
                        rule_id="quality.public_type_hints_required",
                        file=path,
                        line=getattr(func, "lineno", None),
                        message=f"Public function '{func.name}' must have type hints (no Any, return required).",
                    )
                )

            if not (
                is_airflow_dag_function(func) or is_airflow_task_group_function(func)
            ):
                flen = function_length_lines(func)
                if flen > 25:
                    violations.append(
                        Violation(
                            rule_id="organization.function_length",
                            file=path,
                            line=getattr(func, "lineno", None),
                            message=f"Function '{func.name}' is {flen} lines; should be < 25.",
                        )
                    )
    except SyntaxError as e:
        violations.append(
            Violation(
                rule_id="syntax.parse_error",
                file=path,
                line=e.lineno,
                message=f"Syntax error prevents analysis: {e.msg}",
            )
        )

    pkg_root = package_root_for_file(Path(path))
    if pkg_root is not None:
        count_files = count_python_files_in_package(pkg_root)
        if count_files > 7:
            violations.append(
                Violation(
                    rule_id="structure.max_files_per_package",
                    file=path,
                    line=None,
                    message=f"Package '{pkg_root}' has {count_files} Python files; should be <= 7.",
                )
            )

    return violations


def audit_changed_python_files(
    base_ref: str, head_ref: str, *, package_dir: Optional[Path] = None
) -> Tuple[List[str], List[Violation]]:
    files = filter_python_files(changed_files(base_ref, head_ref))
    if package_dir is not None:
        files = [f for f in files if is_within_dir(Path(f), package_dir)]
    violations: List[Violation] = []
    for f in files:
        violations.extend(audit_file(f))
    return files, violations


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    files, violations = audit_changed_python_files(args.base, args.head)
    status = "pass" if not violations else "fail"

    report = {
        "status": status,
        "base_ref": args.base,
        "head_ref": args.head,
        "changed_python_files": files,
        "violations": [asdict(v) for v in violations],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Status: {status}")
        for v in violations:
            loc = f"{v.file}:{v.line}" if v.line else v.file
            print(f"- {v.rule_id} @ {loc}: {v.message}")

    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
