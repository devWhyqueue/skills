from __future__ import annotations

from semantic.rules import Rule


def build_prompt(
    *,
    rules: list[Rule],
    files: list[str],
    diffs: dict[str, str],
    base_ref: str,
    head_ref: str,
) -> str:
    rules_block = "\n".join([f"- {r.id}: {r.statement}" for r in rules]).strip()

    file_blocks: list[str] = []
    for path in files:
        diff = diffs.get(path, "").rstrip()
        file_blocks.append(
            "\n".join(
                [
                    f"## File: {path}",
                    "```diff",
                    diff if diff else "(no diff content available)",
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
            "- For PASS, include evidence and replace scaffold placeholder messages.",
            "",
            "## Diffs",
            "",
            *file_blocks,
            "",
        ]
    )


def build_file_prompt(
    *,
    rules: list[Rule],
    path: str,
    diff: str,
    base_ref: str,
    head_ref: str,
) -> str:
    rules_block = "\n".join([f"- {r.id}: {r.statement}" for r in rules]).strip()
    diff_block = diff.rstrip()
    return "\n".join(
        [
            "# Semantic Clean Code Review (Single File)",
            "",
            f"Base ref: {base_ref}",
            f"Head ref: {head_ref}",
            f"File: {path}",
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
            "- Emit exactly one entry for this file.",
            "- Emit exactly one entry per SEMANTIC rule id.",
            "- Use NA only when a rule is not applicable to this file.",
            "- For FAIL or NEEDS_HUMAN, include at least one evidence item.",
            "- For PASS, include evidence and replace scaffold placeholder messages.",
            "",
            "## Diff",
            "",
            "```diff",
            diff_block if diff_block else "(no diff content available)",
            "```",
            "",
        ]
    )


def build_index_prompt(
    *,
    files_info: list[dict[str, str]],
    base_ref: str,
    head_ref: str,
) -> str:
    lines = [
        "# Semantic Clean Code Review (Index)",
        "",
        f"Base ref: {base_ref}",
        f"Head ref: {head_ref}",
        "",
        "This run now writes one ledger per file to avoid mass approval.",
        "Review each file ledger and prompt below, then re-run the skill.",
        "",
        "## Files",
    ]
    for entry in files_info:
        path = entry.get("path", "")
        ledger = entry.get("ledger_path", "")
        prompt = entry.get("prompt_path", "")
        lines.extend(
            [
                f"- {path}",
                f"  - ledger: {ledger}",
                f"  - prompt: {prompt}",
            ]
        )
    lines.append("")
    return "\n".join(lines)
