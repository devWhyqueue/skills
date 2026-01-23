import unittest

from sonar.api import _is_exempt_from_sonar_s138


class TestSonarS138Filter(unittest.TestCase):
    def test_exempts_dag_decorated_function(self) -> None:
        source = """\
from airflow.decorators import dag

@dag
def my_dag():
    x = 1
    return x
"""
        self.assertTrue(_is_exempt_from_sonar_s138(source, 5))

    def test_exempts_task_group_decorated_function(self) -> None:
        source = """\
from airflow.decorators import task_group

@task_group()
def my_group():
    x = 1
    return x
"""
        self.assertTrue(_is_exempt_from_sonar_s138(source, 5))

    def test_does_not_exempt_plain_function(self) -> None:
        source = """\
def f():
    return 1
"""
        self.assertFalse(_is_exempt_from_sonar_s138(source, 2))


if __name__ == "__main__":
    unittest.main()
