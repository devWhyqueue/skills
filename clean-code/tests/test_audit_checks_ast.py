"""Tests for audit.checks_ast."""
from __future__ import annotations

import ast

import pytest

from audit.checks_ast import (
    all_args_typed,
    detect_imports_not_at_file_top,
    detect_non_snake_case_identifiers,
    function_length_lines,
    has_docstring,
    is_airflow_length_exempt,
    iter_public_functions,
)


def test_iter_public_functions() -> None:
    tree = ast.parse("def _private(): pass\ndef public(): pass\n")
    funcs = list(iter_public_functions(tree))
    assert len(funcs) == 1
    assert funcs[0].name == "public"


def test_has_docstring_true() -> None:
    tree = ast.parse('def f() -> None:\n    """Yes."""\n    pass\n')
    func = tree.body[0]
    assert has_docstring(func) is True


def test_has_docstring_false() -> None:
    tree = ast.parse("def f() -> None:\n    pass\n")
    func = tree.body[0]
    assert has_docstring(func) is False


def test_all_args_typed_full() -> None:
    tree = ast.parse("def f(x: int, y: str) -> bool:\n    return True\n")
    func = tree.body[0]
    assert all_args_typed(func) is True


def test_all_args_typed_missing_arg() -> None:
    tree = ast.parse("def f(x):\n    pass\n")
    func = tree.body[0]
    assert all_args_typed(func) is False


def test_all_args_typed_missing_return() -> None:
    tree = ast.parse("def f(x: int):\n    pass\n")
    func = tree.body[0]
    assert all_args_typed(func) is False


def test_all_args_typed_any_false() -> None:
    tree = ast.parse("def f(x: Any) -> Any:\n    pass\n")
    func = tree.body[0]
    assert all_args_typed(func) is False


def test_function_length_lines() -> None:
    tree = ast.parse("def f() -> None:\n    a = 1\n    b = 2\n    return a + b\n")
    func = tree.body[0]
    assert function_length_lines(func) == 3


def test_function_length_lines_single_pass() -> None:
    tree = ast.parse("def f() -> None:\n    pass\n")
    func = tree.body[0]
    # pass is one line of body
    assert function_length_lines(func) == 1


def test_is_airflow_length_exempt_dag() -> None:
    tree = ast.parse("@dag\ndef my_dag() -> None:\n    pass\n")
    func = tree.body[0]
    assert is_airflow_length_exempt(func) is True


def test_is_airflow_length_exempt_task_group() -> None:
    tree = ast.parse("@task_group\ndef tg() -> None:\n    pass\n")
    func = tree.body[0]
    assert is_airflow_length_exempt(func) is True


def test_is_airflow_length_exempt_plain() -> None:
    tree = ast.parse("def plain() -> None:\n    pass\n")
    func = tree.body[0]
    assert is_airflow_length_exempt(func) is False


def test_detect_imports_not_at_file_top_none() -> None:
    source = '"""Doc."""\nfrom __future__ import annotations\nimport os\nx = 1\n'
    tree = ast.parse(source)
    hits = detect_imports_not_at_file_top(source, tree)
    assert hits == []


def test_detect_imports_not_at_file_top_after_code() -> None:
    source = '"""Doc."""\nx = 1\nimport os\n'
    tree = ast.parse(source)
    hits = detect_imports_not_at_file_top(source, tree)
    assert len(hits) >= 1


def test_detect_non_snake_case_function_name() -> None:
    tree = ast.parse("def myFunction() -> None:\n    pass\n")
    hits = detect_non_snake_case_identifiers(tree)
    assert any("myFunction" in ev for _, ev in hits)


def test_detect_non_snake_case_parameter() -> None:
    tree = ast.parse("def f(myParam: int) -> None:\n    pass\n")
    hits = detect_non_snake_case_identifiers(tree)
    assert any("myParam" in ev for _, ev in hits)


def test_detect_non_snake_case_snake_ok() -> None:
    tree = ast.parse("def my_func(my_param: int) -> None:\n    pass\n")
    hits = detect_non_snake_case_identifiers(tree)
    assert len(hits) == 0


def test_detect_non_snake_case_constant_ok() -> None:
    tree = ast.parse("MAX_SIZE = 42\n")
    hits = detect_non_snake_case_identifiers(tree)
    assert len(hits) == 0


def test_detect_non_snake_case_pascal_ok() -> None:
    tree = ast.parse("TypeAlias = int\n")
    hits = detect_non_snake_case_identifiers(tree)
    assert len(hits) == 0
