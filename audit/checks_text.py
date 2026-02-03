from __future__ import annotations

import re


def detect_broad_except(source: str) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for lines with broad except Exception/BaseException."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(r"^\s*except\s+(Exception|BaseException)\s*:", line):
            hits.append((i, line.strip()))
    return hits


def detect_print_statements(source: str) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for lines that call the print builtin."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"\bprint\s*\(", line):
            hits.append((i, line.strip()))
    return hits


def detect_commented_out_code(source: str) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for lines that look like commented-out code."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        s = line.lstrip()
        if not s.startswith("#"):
            continue
        if re.search(
            r"#\s*(def |class |import |from |if |for |while |try:|except |with )", s
        ):
            hits.append((i, line.strip()))
    return hits


def detect_local_imports(source: str) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for import/from not at column 0."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s+(import|from)\s+\w+", line):
            hits.append((i, line.strip()))
    return hits


def detect_mixed_spark_sql_and_pyspark_api(source: str) -> bool:
    """Return True if source uses both spark.sql() and DataFrame API."""
    has_sql = bool(re.search(r"\bspark\s*\.\s*sql\s*\(", source))
    has_df_api = bool(
        re.search(
            r"\.\s*(select|where|filter|groupBy|join|withColumn|agg)\s*\(", source
        )
    )
    return has_sql and has_df_api


def _file_level_violation_tuples(
    path_str: str, source: str
) -> list[tuple[str, int | None, str, str | None]]:
    """File-level checks: LOC and mixed Spark; return (rule_id, line, message, evidence)."""
    from .files import count_lines

    out: list[tuple[str, int | None, str, str | None]] = []
    loc = count_lines(source)
    if loc > 250:
        out.append(
            ("structure.file_max_loc", None, f"File exceeds 250 lines ({loc}).", None)
        )
    if detect_mixed_spark_sql_and_pyspark_api(source):
        out.append(
            (
                "structure.no_mixed_spark_styles",
                None,
                "File appears to mix Spark SQL (spark.sql) and PySpark DataFrame API.",
                None,
            )
        )
    return out


def _line_based_violation_tuples(
    path_str: str, source: str
) -> list[tuple[str, int | None, str, str | None]]:
    """Line-based checks: print, except, commented code, local imports."""
    out: list[tuple[str, int | None, str, str | None]] = []
    for ln, ev in detect_print_statements(source):
        out.append(
            ("organization.no_print", ln, "Use logging instead of direct output.", ev)
        )
    for ln, ev in detect_broad_except(source):
        out.append(
            (
                "quality.no_broad_exception",
                ln,
                "Avoid broad except Exception/BaseException; catch specific exceptions.",
                ev,
            )
        )
    for ln, ev in detect_commented_out_code(source):
        out.append(
            (
                "organization.no_commented_code",
                ln,
                "Commented-out code blocks are not allowed.",
                ev,
            )
        )
    for ln, ev in detect_local_imports(source):
        out.append(
            (
                "organization.imports_top_level_only",
                ln,
                "Imports must be top-level only (no local imports).",
                ev,
            )
        )
    return out


def collect_text_violation_tuples(
    path_str: str, source: str
) -> list[tuple[str, int | None, str, str | None]]:
    """Run text-based checks; return (rule_id, line, message, evidence) tuples."""
    out = _file_level_violation_tuples(path_str, source)
    out.extend(_line_based_violation_tuples(path_str, source))
    return out
