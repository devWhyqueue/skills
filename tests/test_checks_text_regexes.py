from __future__ import annotations

from audit.checks_text import (
    collect_text_violation_tuples,
    detect_broad_except,
    detect_commented_out_code,
    detect_local_imports,
    detect_mixed_spark_sql_and_pyspark_api,
    detect_print_statements,
)


def test_detect_mixed_spark_sql_and_df_api_does_not_error() -> None:
    source = """
def f(spark):
    df = spark.sql("select 1 as a")
    df = df.select("a")
    return df
"""
    assert detect_mixed_spark_sql_and_pyspark_api(source) is True


def test_detect_broad_except() -> None:
    source = "try:\n    pass\nexcept Exception:\n    pass\n"
    hits = detect_broad_except(source)
    assert len(hits) >= 1
    assert any("Exception" in ev for _, ev in hits)


def test_detect_print_statements() -> None:
    source = "x = 1\nprint(x)\n"
    hits = detect_print_statements(source)
    assert len(hits) >= 1


def test_detect_print_comment_ignored() -> None:
    source = "# print(x)\n"
    hits = detect_print_statements(source)
    assert len(hits) == 0


def test_detect_commented_out_code() -> None:
    source = "# def old(): pass\n"
    hits = detect_commented_out_code(source)
    assert len(hits) >= 1


def test_detect_local_imports() -> None:
    source = "def f():\n    import os\n"
    hits = detect_local_imports(source)
    assert len(hits) >= 1


def test_collect_text_violation_tuples_print() -> None:
    source = '"""Mod."""\nprint("x")\n'
    out = collect_text_violation_tuples("f.py", source)
    assert any(t[0] == "organization.no_print" for t in out)


def test_collect_text_violation_tuples_broad_except() -> None:
    source = "try:\n    pass\nexcept Exception:\n    pass\n"
    out = collect_text_violation_tuples("f.py", source)
    assert any(t[0] == "quality.no_broad_exception" for t in out)


def test_collect_text_violation_tuples_file_loc() -> None:
    source = "\n".join(["x = 1"] * 260)
    out = collect_text_violation_tuples("f.py", source)
    assert any(t[0] == "structure.file_max_loc" for t in out)
