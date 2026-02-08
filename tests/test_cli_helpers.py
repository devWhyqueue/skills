"""Tests for cli.helpers."""
from __future__ import annotations

import pytest

from cli.helpers import semantic_failure_summary


def test_semantic_failure_summary_pass_returns_none() -> None:
    assert semantic_failure_summary({"status": "pass"}) is None
    assert semantic_failure_summary({"status": ""}) is None
    assert semantic_failure_summary({}) is None


def test_semantic_failure_summary_pending() -> None:
    msg = semantic_failure_summary(
        {"status": "pending", "ledger_path": "/path/ledger.yml"}
    )
    assert msg is not None
    assert "pending" in msg.lower()
    assert "ledger" in msg.lower()


def test_semantic_failure_summary_requires_reviewer() -> None:
    msg = semantic_failure_summary(
        {
            "status": "requires_reviewer",
            "summary": {"fails": 2, "needs_human": 1},
            "ledger_path": "/x",
        }
    )
    assert msg is not None
    assert "reviewer" in msg.lower()
    assert "2" in msg
    assert "1" in msg


def test_semantic_failure_summary_failed() -> None:
    msg = semantic_failure_summary(
        {
            "status": "fail",
            "summary": {"fails": 3, "needs_human": 0},
            "ledger_path": "/y",
        }
    )
    assert msg is not None
    assert "fail" in msg.lower()
    assert "3" in msg


def test_semantic_failure_summary_summary_not_dict() -> None:
    msg = semantic_failure_summary(
        {"status": "fail", "summary": "string", "ledger_path": None}
    )
    assert msg is not None
    assert "fail" in msg.lower()
