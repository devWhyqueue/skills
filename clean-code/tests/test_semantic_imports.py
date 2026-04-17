from __future__ import annotations

import importlib


def test_semantic_package_can_import() -> None:
    importlib.import_module("semantic")


def test_semantic_gate_can_import() -> None:
    module = importlib.import_module("semantic.gate")
    assert hasattr(module, "run_semantic_gate_if_enabled")
