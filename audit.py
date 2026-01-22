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
    severity: str  # "error" | "warn"
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
    p = subprocess.run(["git", "rev-parse", "--verify", ref], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    return [l.strip() for l in out.splitlines() if l.strip()]


def filter_python_files(files: Iterable[str]) -> List[str]:
    return [f for f in files if f.endswith(".py") and Path(f).exists()]


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
    if getattr(func, "end_lineno", None) is None or getattr(func, "lineno", None) is None:
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
        if re.search(r"#\s*(def |class |import |from |if |for |while |try:|except |with )", s):
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


def detect_mixed_spark_sql_and_pyspark_api(source: str) -> bool:
    has_sql = bool(re.search(r"\bspark\s*\.\s*sql\s*\(", source))
    has_df_api = bool(re.search(r"\.\s*(select|where|filter|groupBy|join|withColumn|agg)\s*\(", source))
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
        violations.append(Violation(
            rule_id="structure.file_max_loc",
            severity="error",
            file=path,
            line=None,
            message=f"File exceeds 250 lines ({loc}).",
        ))

    if detect_mixed_spark_sql_and_pyspark_api(source):
        violations.append(Violation(
            rule_id="structure.no_mixed_spark_styles",
            severity="error",
            file=path,
            line=None,
            message="File appears to mix Spark SQL (spark.sql) and PySpark DataFrame API.",
        ))

    for line_no, evidence in detect_print_statements(source):
        violations.append(Violation(
            rule_id="organization.no_print",
            severity="error",
            file=path,
            line=line_no,
            message="print() is prohibited; use logging.",
            evidence=evidence,
        ))

    for line_no, evidence in detect_broad_except(source):
        violations.append(Violation(
            rule_id="quality.no_broad_exception",
            severity="error",
            file=path,
            line=line_no,
            message="Avoid broad except Exception/BaseException; catch specific exceptions.",
            evidence=evidence,
        ))

    for line_no, evidence in detect_commented_out_code(source):
        violations.append(Violation(
            rule_id="organization.no_commented_code",
            severity="error",
            file=path,
            line=line_no,
            message="Commented-out code blocks are not allowed.",
            evidence=evidence,
        ))

    for line_no, evidence in detect_local_imports(source):
        violations.append(Violation(
            rule_id="organization.imports_top_level_only",
            severity="error",
            file=path,
            line=line_no,
            message="Imports must be top-level only (no local imports).",
            evidence=evidence,
        ))

    try:
        tree = ast.parse(source)
        for func in iter_public_functions(tree):
            if not has_docstring(func):
                violations.append(Violation(
                    rule_id="quality.public_docstring_required",
                    severity="error",
                    file=path,
                    line=getattr(func, "lineno", None),
                    message=f"Public function '{func.name}' must have a docstring.",
                ))

            if not all_args_typed(func):
                violations.append(Violation(
                    rule_id="quality.public_type_hints_required",
                    severity="error",
                    file=path,
                    line=getattr(func, "lineno", None),
                    message=f"Public function '{func.name}' must have type hints (no Any, return required).",
                ))

            if not is_airflow_dag_function(func):
                flen = function_length_lines(func)
                if flen > 25:
                    violations.append(Violation(
                        rule_id="organization.function_length",
                        severity="warn",
                        file=path,
                        line=getattr(func, "lineno", None),
                        message=f"Function '{func.name}' is {flen} lines; should be < 25.",
                    ))
    except SyntaxError as e:
        violations.append(Violation(
            rule_id="syntax.parse_error",
            severity="error",
            file=path,
            line=e.lineno,
            message=f"Syntax error prevents analysis: {e.msg}",
        ))

    pkg_root = package_root_for_file(Path(path))
    if pkg_root is not None:
        count_files = count_python_files_in_package(pkg_root)
        if count_files > 7:
            violations.append(Violation(
                rule_id="structure.max_files_per_package",
                severity="warn",
                file=path,
                line=None,
                message=f"Package '{pkg_root}' has {count_files} Python files; should be <= 7.",
            ))

    return violations


def audit_changed_python_files(base_ref: str, head_ref: str) -> Tuple[List[str], List[Violation]]:
    files = filter_python_files(changed_files(base_ref, head_ref))
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
    status = "pass" if not any(v.severity == "error" for v in violations) else "fail"

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
            print(f"- [{v.severity}] {v.rule_id} @ {loc}: {v.message}")

    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
