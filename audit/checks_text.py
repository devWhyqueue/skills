from __future__ import annotations

import re


def detect_broad_except(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(r"^\\s*except\\s+(Exception|BaseException)\\s*:", line):
            hits.append((i, line.strip()))
    return hits


def detect_print_statements(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"\\bprint\\s*\\(", line):
            hits.append((i, line.strip()))
    return hits


def detect_commented_out_code(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        s = line.lstrip()
        if not s.startswith("#"):
            continue
        if re.search(
            r"#\\s*(def |class |import |from |if |for |while |try:|except |with )", s
        ):
            hits.append((i, line.strip()))
    return hits


def detect_local_imports(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if re.match(r"^\\s+(import|from)\\s+\\w+", line):
            hits.append((i, line.strip()))
    return hits


def detect_mixed_spark_sql_and_pyspark_api(source: str) -> bool:
    has_sql = bool(re.search(r"\\bspark\\s*\\.\\s*sql\\s*\\(", source))
    has_df_api = bool(
        re.search(
            r"\\.\\s*(select|where|filter|groupBy|join|withColumn|agg)\\s*\\(", source
        )
    )
    return has_sql and has_df_api
