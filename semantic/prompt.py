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
            "",
            "## Diffs",
            "",
            *file_blocks,
            "",
        ]
    )
