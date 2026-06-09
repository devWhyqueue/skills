"""Tests for audit.auditor (audit_file, audit_python_files, Violation)."""
from __future__ import annotations

from pathlib import Path

import pytest

from audit.auditor import (
    MAX_PACKAGE_CHILDREN,
    Violation,
    _count_package_children,
    audit_file,
    audit_python_files,
)


def test_audit_file_clean(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text('"""Doc."""\nfrom __future__ import annotations\ndef foo(x: int) -> str:\n    """Bar."""\n    return str(x)\n')
    violations = audit_file(p)
    assert isinstance(violations, list)
    # May have structure.file_max_loc if long; we keep file short
    assert all(isinstance(v, Violation) for v in violations)


def test_audit_file_syntax_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("def x(\n  invalid\n")
    violations = audit_file(p)
    assert len(violations) >= 1
    assert any(v.rule_id == "syntax.parse_error" for v in violations)


def test_audit_file_no_docstring(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def public_func(x: int) -> int:\n    return x + 1\n")
    violations = audit_file(p)
    assert any(v.rule_id == "quality.public_docstring_required" for v in violations)


def test_audit_file_no_type_hints(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text('"""Mod."""\ndef public_func(x):\n    """Return x."""\n    return x\n')
    violations = audit_file(p)
    assert any(v.rule_id == "quality.public_type_hints_required" for v in violations)


def test_audit_file_import_not_at_top(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text('"""Mod."""\nx = 1\nimport os\n')
    violations = audit_file(p)
    assert any(v.rule_id == "organization.imports_at_file_top" for v in violations)


def test_audit_file_print(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text('"""Mod."""\ndef f() -> None:\n    print("x")\n')
    violations = audit_file(p)
    assert any(v.rule_id == "organization.no_print" for v in violations)


def test_audit_python_files_empty() -> None:
    files, violations = audit_python_files([])
    assert files == []
    assert violations == []


def test_audit_python_files_filtered(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text('"""X."""\ndef f() -> None:\n    pass\n')
    (tmp_path / "b.txt").write_text("x")
    files, violations = audit_python_files(
        [str(tmp_path / "a.py"), str(tmp_path / "b.txt")]
    )
    assert len(files) == 1
    assert str(tmp_path / "a.py") in files


def test_audit_python_files_package_dir(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "m.py").write_text('"""X."""\ndef f() -> None:\n    pass\n')
    (tmp_path / "other.py").write_text("x = 1\n")
    files, _ = audit_python_files(
        [str(pkg / "m.py"), str(tmp_path / "other.py")],
        package_dir=tmp_path / "src",
    )
    assert len(files) == 1
    assert str(pkg / "m.py") in files


def test_violation_dataclass() -> None:
    v = Violation(rule_id="r", file="f.py", line=1, message="m", evidence="e")
    assert v.rule_id == "r"
    assert v.file == "f.py"
    assert v.line == 1
    assert v.message == "m"
    assert v.evidence == "e"


def test_count_package_children_ignores_pycache(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("")
    (pkg / "subpkg").mkdir()
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"x")
    assert _count_package_children(pkg) == 3


def test_audit_file_package_child_limit(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for idx in range(MAX_PACKAGE_CHILDREN - 2):
        (pkg / f"mod_{idx}.py").write_text('"""Mod."""\n')
    ok_violations = audit_file(pkg / "mod_0.py")
    assert not any(v.rule_id == "structure.max_files_per_package" for v in ok_violations)

    (pkg / f"mod_{MAX_PACKAGE_CHILDREN - 2}.py").write_text('"""Mod."""\n')
    over_violations = audit_file(pkg / "mod_0.py")
    assert any(v.rule_id == "structure.max_files_per_package" for v in over_violations)


def test_audit_file_package_counts_subfolders(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text('"""Mod."""\n')
    for idx in range(MAX_PACKAGE_CHILDREN - 3):
        (pkg / f"sub_{idx}").mkdir()
    ok_violations = audit_file(pkg / "mod.py")
    assert not any(v.rule_id == "structure.max_files_per_package" for v in ok_violations)

    (pkg / f"sub_{MAX_PACKAGE_CHILDREN - 3}").mkdir()
    over_violations = audit_file(pkg / "mod.py")
    assert any(v.rule_id == "structure.max_files_per_package" for v in over_violations)
