from __future__ import annotations

from pathlib import Path
from typing import Any

from git import diff_for_file_uncommitted
from semantic.ledger import dump_yaml, new_ledger, normalize_ledger
from semantic.utils import load_rules
from semantic.utils import Rule, posix, safe_slug, truncate, utc_now_iso

_FILE_PROMPT_YAML_SCHEMA = [
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
]
_FILE_PROMPT_RULES_BULLETS = [
    "Emit exactly one entry for this file.",
    "Emit exactly one entry per SEMANTIC rule id.",
    "Use NA only when a rule is not applicable to this file.",
    "For FAIL or NEEDS_HUMAN, include at least one evidence item.",
    "For PASS, include evidence and replace scaffold placeholder messages.",
]


def _rules_block(rules: list[Rule]) -> str:
    return "\n".join([f"- {r.id}: {r.statement}" for r in rules]).strip()


def _file_prompt_sections(rules: list[Rule], path: str, diff: str) -> list[str]:
    """Build the list of sections for a single-file prompt."""
    schema = "\n".join([""] + _FILE_PROMPT_YAML_SCHEMA + [""])
    rules_text = _rules_block(rules) or "(none)"
    rules_list = "\n".join(f"- {b}" for b in _FILE_PROMPT_RULES_BULLETS)
    diff_block = diff.rstrip() or "(no diff content available)"
    return [
        "# Semantic Clean Code Review (Single File)",
        "",
        "Context: uncommitted changes vs HEAD",
        f"File: {path}",
        "",
        "## SEMANTIC rules to evaluate",
        rules_text,
        "",
        "## Output format (MUST be valid YAML)",
        "Return ONLY YAML matching this schema exactly:",
        schema,
        "Rules:",
        rules_list,
        "",
        "## Diff",
        "",
        "```diff",
        diff_block,
        "```",
        "",
    ]


def build_file_prompt(
    *,
    rules: list[Rule],
    path: str,
    diff: str,
) -> str:
    """Build the semantic review prompt for a single file and its diff."""
    return "\n".join(_file_prompt_sections(rules, path, diff))


def _index_prompt_files_lines(files_info: list[dict[str, str]]) -> list[str]:
    lines = []
    for entry in files_info:
        path = entry.get("path", "")
        ledger = entry.get("ledger_path", "")
        prompt = entry.get("prompt_path", "")
        lines.extend([f"- {path}", f"  - ledger: {ledger}", f"  - prompt: {prompt}"])
    return lines


def build_index_prompt(*, files_info: list[dict[str, str]]) -> str:
    """Build the index prompt listing files and their ledger/prompt paths."""
    header = [
        "# Semantic Clean Code Review (Index)",
        "",
        "Context: uncommitted changes vs HEAD",
        "",
        "This run intentionally shows one file at a time to avoid mass approval.",
        "Review the ledger and prompt below, then re-run the skill for the next file.",
        "",
        "## Files",
    ]
    body = (
        _index_prompt_files_lines(files_info)
        if files_info
        else ["- (all files reviewed)"]
    )
    return "\n".join([*header, *body, ""])


def _diffs_for_files(files: list[str], max_diff_chars: int) -> dict[str, str]:
    """Build path -> truncated diff map."""
    return {
        path: truncate(diff_for_file_uncommitted(path), max_chars=max_diff_chars)
        for path in files
    }


def _ensure_scaffold_dirs(out_dir: Path) -> tuple[Path, Path]:
    """Create out_dir, ledgers, prompts; return (ledger_dir, prompt_dir)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_dir = out_dir / "ledgers"
    prompt_dir = out_dir / "prompts"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    return ledger_dir, prompt_dir


def _write_file_ledger_and_prompt(
    *,
    path: str,
    rules_path: Path,
    rules: list[Rule],
    ledger_dir: Path,
    prompt_dir: Path,
    diffs: dict[str, str],
) -> dict[str, str]:
    """Write per-file ledger and prompt; return files_info entry."""
    slug = safe_slug(path)
    file_ledger_path = ledger_dir / f"{slug}.yml"
    file_prompt_path = prompt_dir / f"{slug}.md"
    file_prompt_path.write_text(
        build_file_prompt(rules=rules, path=path, diff=diffs.get(path, "")),
        encoding="utf-8",
    )
    file_ledger = new_ledger(rules_path=rules_path, files=[path], rules=rules)
    file_normalized = normalize_ledger(ledger=file_ledger, files=[path], rules=rules)
    file_normalized["meta"] = file_ledger["meta"]
    if not file_ledger_path.exists():
        file_ledger_path.write_text(dump_yaml(file_normalized), encoding="utf-8")
    return {
        "path": path,
        "ledger_path": posix(file_ledger_path),
        "prompt_path": posix(file_prompt_path),
    }


def _build_index_ledger(
    *,
    rules_path: Path,
    ledger_dir: Path,
    files_info: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the index ledger dict."""
    return {
        "version": 1,
        "meta": {
            "generated_at_utc": utc_now_iso(),
            "rules_path": posix(rules_path),
            "mode": "single_file",
            "ledger_dir": posix(ledger_dir),
            "phase": "scaffold",
        },
        "summary": {"fails": 0, "needs_human": 0},
        "files": files_info,
    }


def _write_index_artifacts(
    out_dir: Path,
    index_ledger: dict[str, Any],
    files_info: list[dict[str, str]],
) -> dict[str, Any]:
    """Write index prompt, template, and ledger; return result dict."""
    ledger_path = out_dir / "semantic_ledger.yml"
    prompt_path = out_dir / "semantic_prompt.md"
    prompt_path.write_text(build_index_prompt(files_info=files_info), encoding="utf-8")
    ledger_template_path = out_dir / "semantic_ledger.template.yml"
    ledger_template_path.write_text(dump_yaml(index_ledger), encoding="utf-8")
    ledger_path.write_text(dump_yaml(index_ledger), encoding="utf-8")
    return {
        "status": "scaffolded",
        "ledger_path": posix(ledger_path),
        "ledger_template_path": posix(ledger_template_path),
        "prompt_path": posix(prompt_path),
        "summary": index_ledger["summary"],
    }


def run_scaffold(
    *,
    files: list[str],
    rules_path: Path,
    out_dir: Path,
    max_diff_chars: int = 120_000,
) -> dict[str, Any]:
    """Generate semantic ledgers and prompts for the given files under out_dir."""
    rules = load_rules(rules_path)
    diffs = _diffs_for_files(files, max_diff_chars)
    ledger_dir, prompt_dir = _ensure_scaffold_dirs(out_dir)
    files_info = [
        _write_file_ledger_and_prompt(
            path=path,
            rules_path=rules_path,
            rules=rules,
            ledger_dir=ledger_dir,
            prompt_dir=prompt_dir,
            diffs=diffs,
        )
        for path in files
    ]
    index_ledger = _build_index_ledger(
        rules_path=rules_path, ledger_dir=ledger_dir, files_info=files_info
    )
    result = _write_index_artifacts(out_dir, index_ledger, files_info)
    result["semantic_rules"] = [{"id": r.id, "statement": r.statement} for r in rules]
    return result
