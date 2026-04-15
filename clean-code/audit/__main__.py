from __future__ import annotations

import argparse
import logging
import json
from dataclasses import asdict

from .auditor import audit_python_files
from .files import exclude_test_folders, filter_python_files
from git import uncommitted_changed_files

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run audit on uncommitted Python files; return 0 if pass, 2 if violations."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files = exclude_test_folders(filter_python_files(uncommitted_changed_files()))
    files, violations = audit_python_files(files)
    status = "pass" if not violations else "fail"

    report = {
        "status": status,
        "changed_python_files": files,
        "violations": [asdict(v) for v in violations],
    }

    if args.json:
        logger.info(json.dumps(report, indent=2))
    else:
        logger.info(f"Status: {status}")
        for v in violations:
            loc = f"{v.file}:{v.line}" if v.line else v.file
            logger.info(f"- {v.rule_id} @ {loc}: {v.message}")

    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
