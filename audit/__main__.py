from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .auditor import audit_changed_python_files
from git import detect_base_ref


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files, violations = audit_changed_python_files(args.base, args.head)
    status = "pass" if not violations else "fail"

    report = {
        "status": status,
        "base_ref": args.base,
        "head_ref": args.head,
        "changed_python_files": files,
        "violations": [asdict(v) for v in violations],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Status: {status}")
        for v in violations:
            loc = f"{v.file}:{v.line}" if v.line else v.file
            print(f"- {v.rule_id} @ {loc}: {v.message}")

    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
