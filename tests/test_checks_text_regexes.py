from __future__ import annotations

from audit.checks_text import detect_mixed_spark_sql_and_pyspark_api


def test_detect_mixed_spark_sql_and_df_api_does_not_error() -> None:
    source = """
def f(spark):
    df = spark.sql("select 1 as a")
    df = df.select("a")
    return df
"""
    assert detect_mixed_spark_sql_and_pyspark_api(source) is True
