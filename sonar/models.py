from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SonarIssue:
    key: str
    rule: str
    severity: str
    message: str
    component: str
    line: Optional[int]
    type: str


@dataclass
class SonarGateResult:
    status: str  # OK | ERROR | NONE (evaluated, may be scoped)
    raw_status: str  # OK | ERROR | NONE (server-reported)
    conditions: List[Dict[str, Any]]
    issues: List[SonarIssue]
    issues_stats: Dict[str, int]
