from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from audit import detect_base_ref

try:
    import yaml
except Exception as e:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _yaml_import_error = e


ALLOWED_STATUSES = {"PASS", "FAIL", "NEEDS_HUMAN", "NA"}


@dataclass(frozen=True)
class SemanticRule:
    rule_id: str
    statement: str


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr


def _require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError(
            "Missing dependency: PyYAML is required for semantic gate YAML I/O. "
            f"Import error: {_yaml_import_error}"
        )
    return yaml


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _posix(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def git_merge_base(base_ref: str, head_ref: str) -> str:
    code, out, err = _run(["git", "merge-base", base_ref, head_ref])
    if code != 0:
        raise RuntimeError(f"git merge-base failed:\n{err}")
    return out.strip()


def git_changed_files(base_ref: str, head_ref: str) -> List[str]:
    base = git_merge_base(base_ref, head_ref)
    code, out, err = _run(["git", "diff", "--name-only", f"{base}..{head_ref}"])
    if code != 0:
        raise RuntimeError(f"git diff --name-only failed:\n{err}")
    return [line.strip() for line in out.splitlines() if line.strip()]


def filter_existing_python_files(files: List[str]) -> List[str]:
    out: List[str] = []
    for f in files:
        if not f.endswith(".py"):
            continue
        if Path(f).exists():
            out.append(f)
    return out


def git_file_diff(base_ref: str, head_ref: str, path: str) -> str:
    base = git_merge_base(base_ref, head_ref)
    code, out, err = _run(
        [
            "git",
            "diff",
            "--unified=3",
            f"{base}..{head_ref}",
            "--",
            path,
        ]
    )
    if code != 0:
        raise RuntimeError(f"git diff failed for {path}:\n{err}")
    return out


def load_semantic_rules(rules_path: Path) -> List[SemanticRule]:
    y = _require_yaml()
    data = y.safe_load(rules_path.read_text(encoding="utf-8", errors="replace")) or {}
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise RuntimeError(f"Invalid rules file (expected list at rules:): {rules_path}")

    semantic: List[SemanticRule] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        enforcement = str(r.get("enforcement", "")).strip().upper()
        if enforcement != "SEMANTIC":
            continue
        rule_id = str(r.get("id", "")).strip()
        statement = str(r.get("statement", "")).strip()
        if not rule_id or not statement:
            continue
        semantic.append(SemanticRule(rule_id=rule_id, statement=statement))

    semantic = sorted(semantic, key=lambda rr: rr.rule_id)
    if not semantic:
        raise RuntimeError(
            f"No SEMANTIC rules found in {rules_path} (enforcement: SEMANTIC)."
        )
    return semantic


def _truncate(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head].rstrip()
        + "\n\n... (diff truncated) ...\n\n"
        + text[-keep_tail:].lstrip()
    )


def semantic_gate_temp_dir(*, prefix: str = "clean-code-pr-review-semantic-") -> Path:
    base = Path(tempfile.gettempdir())
    out = base / f"{prefix}{os.getpid()}-{int(datetime.now().timestamp())}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def build_prompt(
    *,
    semantic_rules: List[SemanticRule],
    files: List[str],
    diffs: Dict[str, str],
    base_ref: str,
    head_ref: str,
) -> str:
    """
    Build an LLM evaluation prompt that asks for a deterministic YAML ledger.

    The caller is responsible for writing the prompt to disk if desired.
    """
    rules_block = "\n".join(
        [f"- {r.rule_id}: {r.statement}" for r in semantic_rules]
    ).strip()

    file_blocks: List[str] = []
    for f in files:
        d = diffs.get(f, "").rstrip()
        file_blocks.append(
            "\n".join(
                [
                    f"## File: {f}",
                    "```diff",
                    d if d else "(no diff content available)",
                    "```",
                ]
            )
        )

    return "\n".join(
        [
            "# Semantic Clean Code Review",
            "",
            f"Base ref: {base_ref}",
            f"Head ref: {head_ref}",
            "",
            "## SEMANTIC rules to evaluate",
            rules_block if rules_block else "(none)",
            "",
            "## Output format (MUST be valid YAML)",
            "Return ONLY YAML matching this schema exactly:",
            "",
            "version: 1",
            "summary:",
            "  fails: <int>",
            "  needs_human: <int>",
            "files:",
            "  - path: <string>",
            "    rules:",
            "      - id: <CC-..>",
            "        status: PASS|FAIL|NEEDS_HUMAN|NA",
            "        evidence:",
            "          - symbol: <string>",
            "            lines:",
            "              start: <int>",
            "              end: <int>",
            "            message: <string>",
            "",
            "Rules:",
            "- Emit exactly one entry per input file.",
            "- For each file, emit exactly one entry per SEMANTIC rule id.",
            "- Use NA only when a rule is not applicable to that file.",
            "- For FAIL or NEEDS_HUMAN, include at least one evidence item.",
            "",
            "## Diffs",
            "",
            *file_blocks,
            "",
        ]
    )


def new_ledger(
    *,
    rules_path: Path,
    base_ref: str,
    head_ref: str,
    files: List[str],
    semantic_rules: List[SemanticRule],
) -> Dict[str, Any]:
    file_line_counts: Dict[str, int] = {}
    for f in files:
        try:
            file_line_counts[f] = len(
                Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except Exception:
            file_line_counts[f] = 1

    return {
        "version": 1,
        "meta": {
            "generated_at_utc": _utc_now_iso(),
            "rules_path": _posix(rules_path),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": [
            {
                "path": f,
                "rules": [
                    {
                        "id": r.rule_id,
                        "status": "NEEDS_HUMAN",
                        "evidence": [
                            {
                                "symbol": "<module>",
                                "lines": {
                                    "start": 1,
                                    "end": max(1, int(file_line_counts.get(f, 1))),
                                },
                                "message": (
                                    f"Pending semantic review for {r.rule_id}: {r.statement}"
                                ),
                            }
                        ],
                    }
                    for r in semantic_rules
                ],
            }
            for f in files
        ],
    }


def _normalize_evidence_item(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    symbol = str(item.get("symbol", "")).strip()
    message = str(item.get("message", "")).strip()
    lines = item.get("lines", {})
    if not isinstance(lines, dict):
        lines = {}
    start = lines.get("start")
    end = lines.get("end")
    try:
        start_i = int(start)
        end_i = int(end)
    except Exception:
        return None
    if not symbol or not message:
        return None
    if start_i <= 0 or end_i <= 0:
        return None
    if end_i < start_i:
        start_i, end_i = end_i, start_i
    return {"symbol": symbol, "lines": {"start": start_i, "end": end_i}, "message": message}


def normalize_ledger_structure(
    *,
    ledger: Dict[str, Any],
    files: List[str],
    semantic_rules: List[SemanticRule],
) -> Dict[str, Any]:
    """
    Make the ledger deterministic and schema-safe even if content is LLM-generated.

    - Ensures all files/rules exist
    - Normalizes statuses and evidence shape
    - Recomputes summary counts
    """
    rule_ids = [r.rule_id for r in semantic_rules]
    rules_by_id = {r.rule_id: r for r in semantic_rules}

    existing_files = {}
    for f in ledger.get("files", []) if isinstance(ledger.get("files"), list) else []:
        if isinstance(f, dict) and isinstance(f.get("path"), str):
            existing_files[f["path"]] = f

    normalized_files: List[Dict[str, Any]] = []
    fails = 0
    needs_human = 0

    for path in files:
        try:
            file_line_count = len(
                Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except Exception:
            file_line_count = 1

        file_entry = existing_files.get(path, {})
        raw_rules = file_entry.get("rules", [])
        rules_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_rules, list):
            for rr in raw_rules:
                if not isinstance(rr, dict):
                    continue
                rid = str(rr.get("id", "")).strip()
                if rid:
                    rules_map[rid] = rr

        out_rules: List[Dict[str, Any]] = []
        for rid in rule_ids:
            rr = rules_map.get(rid, {})
            status = str(rr.get("status", "NEEDS_HUMAN")).strip().upper()
            if status not in ALLOWED_STATUSES:
                status = "NEEDS_HUMAN"

            evidence_items: List[Dict[str, Any]] = []
            raw_evidence = rr.get("evidence", [])
            if isinstance(raw_evidence, list):
                for item in raw_evidence:
                    norm = _normalize_evidence_item(item)
                    if norm is not None:
                        evidence_items.append(norm)

            if status in {"FAIL", "NEEDS_HUMAN"} and not evidence_items:
                evidence_items = [
                    {
                        "symbol": "<module>",
                        "lines": {"start": 1, "end": max(1, int(file_line_count))},
                        "message": (
                            f"Missing evidence; provide symbol, line range, and message for {rid}."
                        ),
                    }
                ]

            if status == "FAIL":
                fails += 1
            elif status == "NEEDS_HUMAN":
                needs_human += 1

            out_rules.append({"id": rules_by_id[rid].rule_id, "status": status, "evidence": evidence_items})

        normalized_files.append({"path": path, "rules": out_rules})

    version = int(ledger.get("version", 1) or 1)
    return {
        "version": version,
        "summary": {"fails": fails, "needs_human": needs_human},
        "files": normalized_files,
    }


def dump_yaml_deterministic(data: Dict[str, Any]) -> str:
    y = _require_yaml()
    return y.safe_dump(data, sort_keys=False, default_flow_style=False, width=120)


def run_semantic_scaffold(
    *,
    base_ref: str,
    head_ref: str,
    files: List[str],
    rules_path: Path,
    out_dir: Optional[Path] = None,
    max_diff_chars: int = 120_000,
) -> Dict[str, Any]:
    semantic_rules = load_semantic_rules(rules_path)
    diffs = {
        f: _truncate(git_file_diff(base_ref, head_ref, f), max_chars=max_diff_chars)
        for f in files
    }

    out_dir = out_dir or semantic_gate_temp_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "semantic_ledger.yml"
    ledger_template_path = out_dir / "semantic_ledger.template.yml"
    prompt_path = out_dir / "semantic_prompt.md"

    prompt = build_prompt(
        semantic_rules=semantic_rules,
        files=files,
        diffs=diffs,
        base_ref=base_ref,
        head_ref=head_ref,
    )
    prompt_path.write_text(prompt, encoding="utf-8")

    ledger = new_ledger(
        rules_path=rules_path,
        base_ref=base_ref,
        head_ref=head_ref,
        files=files,
        semantic_rules=semantic_rules,
    )

    normalized = normalize_ledger_structure(
        ledger=ledger, files=files, semantic_rules=semantic_rules
    )
    # keep meta deterministically present (normalize strips it)
    normalized["meta"] = ledger["meta"]

    ledger_template_path.write_text(dump_yaml_deterministic(normalized), encoding="utf-8")
    if not ledger_path.exists():
        ledger_path.write_text(dump_yaml_deterministic(normalized), encoding="utf-8")

    return {
        "status": "scaffolded",
        "ledger_path": _posix(ledger_path),
        "ledger_template_path": _posix(ledger_template_path),
        "prompt_path": _posix(prompt_path),
        "summary": normalized["summary"],
        "semantic_rules": [{"id": r.rule_id, "statement": r.statement} for r in semantic_rules],
    }

def load_and_validate_ledger(
    *,
    ledger_path: Path,
    files: List[str],
    rules_path: Path,
) -> Dict[str, Any]:
    y = _require_yaml()
    semantic_rules = load_semantic_rules(rules_path)

    raw_any = y.safe_load(ledger_path.read_text(encoding="utf-8", errors="replace")) or {}
    raw = raw_any if isinstance(raw_any, dict) else {}
    normalized = normalize_ledger_structure(
        ledger=raw, files=files, semantic_rules=semantic_rules
    )

    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    phase = str(meta.get("phase", "")).strip().lower()
    any_reviewed = False
    for f in normalized.get("files", []):
        for r in f.get("rules", []):
            if str(r.get("status", "")).strip().upper() in {"PASS", "FAIL", "NA"}:
                any_reviewed = True
                break
        if any_reviewed:
            break
    if phase != "evaluated" and any_reviewed:
        phase = "evaluated"
    if phase not in {"scaffold", "evaluated"}:
        phase = "evaluated" if any_reviewed else "scaffold"

    normalized["meta"] = {
        **(meta if isinstance(meta, dict) else {}),
        "phase": phase,
    }

    ledger_path.write_text(dump_yaml_deterministic(normalized), encoding="utf-8")

    fails = int(normalized.get("summary", {}).get("fails", 0) or 0)
    needs_human = int(normalized.get("summary", {}).get("needs_human", 0) or 0)

    if phase == "scaffold":
        status = "pending"
    elif fails == 0 and needs_human == 0:
        status = "pass"
    elif needs_human:
        status = "requires_reviewer"
    else:
        status = "fail"

    return {
        "status": status,
        "ledger_path": _posix(ledger_path),
        "summary": normalized["summary"],
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=detect_base_ref("develop"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument(
        "--rules",
        default="clean_code_rules.yml",
        help="Path to rules YAML (default: clean_code_rules.yml).",
    )
    ap.add_argument(
        "--max-diff-chars",
        type=int,
        default=int(os.getenv("SEMANTIC_MAX_DIFF_CHARS", "120000")),
        help="Maximum characters of diff per file included in the prompt.",
    )
    ap.add_argument(
        "--out-dir",
        default="",
        help="Optional directory to write semantic_ledger.yml and semantic_prompt.md.",
    )
    ap.add_argument(
        "--validate",
        action="store_true",
        help="Validate/normalize semantic_ledger.yml (do not regenerate prompt).",
    )
    ap.add_argument(
        "--files-json",
        default="",
        help="Optional JSON array of files to evaluate (otherwise computed from git diff).",
    )
    args = ap.parse_args()

    rules_path = Path(args.rules)
    if not rules_path.exists():
        raise SystemExit(f"Rules file not found: {rules_path}")

    if args.files_json:
        files = json.loads(args.files_json)
        if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
            raise SystemExit("--files-json must be a JSON array of strings")
        files = filter_existing_python_files(files)
    else:
        files = filter_existing_python_files(git_changed_files(args.base, args.head))

    out_dir = Path(args.out_dir) if args.out_dir.strip() else None
    if args.validate:
        if out_dir is None:
            raise SystemExit("--validate requires --out-dir (directory containing semantic_ledger.yml).")
        ledger_path = out_dir / "semantic_ledger.yml"
        if not ledger_path.exists():
            raise SystemExit(f"Ledger not found: {ledger_path}")
        report = load_and_validate_ledger(
            ledger_path=ledger_path, files=files, rules_path=rules_path
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") == "pass" else 2

    report = run_semantic_scaffold(
        base_ref=args.base,
        head_ref=args.head,
        files=files,
        rules_path=rules_path,
        out_dir=out_dir,
        max_diff_chars=int(args.max_diff_chars),
    )

    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
