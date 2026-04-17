"""Shared helpers for CLI (semantic failure summary). Used by runner and gates to avoid circular imports."""

from __future__ import annotations

from typing import Any, Optional


def _semantic_failure_message(
    status: str, fails: int, needs_human: int, ledger_path: object
) -> str:
    if status == "pending":
        return (
            "Semantic ledger pending evaluation. "
            f"Review '{ledger_path}' and the per-file ledgers it references, set PASS/FAIL/NA "
            "(NEEDS_HUMAN only if truly undecidable), then re-run."
        )
    if status == "requires_reviewer":
        return (
            f"Semantic gate requires reviewer input: fails={fails}, needs_human={needs_human} "
            f"(ledger: {ledger_path})."
        )
    return f"Semantic gate failed: fails={fails}, needs_human={needs_human} (ledger: {ledger_path})."


def semantic_failure_summary(semantic_report: dict[str, Any]) -> Optional[str]:
    """Return a short summary string if semantic gate failed; otherwise None."""
    sem_status = str(semantic_report.get("status", "")).strip()
    if sem_status in {"", "pass"}:
        return None
    sem_summary = (
        semantic_report.get("summary", {}) if isinstance(semantic_report, dict) else {}
    )
    if not isinstance(sem_summary, dict):
        sem_summary = {}
    sem_fails = int(sem_summary.get("fails", 0) or 0)
    sem_needs = int(sem_summary.get("needs_human", 0) or 0)
    ledger_path = semantic_report.get("ledger_path")
    return _semantic_failure_message(sem_status, sem_fails, sem_needs, ledger_path)
