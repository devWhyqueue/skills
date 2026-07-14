---
name: clean-code
description: Review and automatically fix uncommitted or untracked Python files against the bundled clean-code rules. Use after editing Python code or when asked to check Python code quality.
---

Run from the calling project root:

`uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py"`

- Default: audit, Pyright, Vulture, and pytest on changed non-test `*.py` files.
- Use `--scope <package-or-path>` to restrict files, `--vulture-scope <paths>` to set scan roots, and `--min-coverage <N>` to require coverage.
- Use `--full` to add Sonar and semantic review; use `--json` only when the complete machine-readable report is needed.
- Default output is concise text. Exit `0` passes, `2` fails, and `3` signals an internal error.

Fix reported violations without relaxing tools or rules, then rerun. For semantic review, evaluate each generated ledger entry as `PASS`, `FAIL`, or `NA` (`NEEDS_HUMAN` only when undecidable); keep rerunning until no pending files remain.

Ruff formatting is canonical and length limits are checked afterward. Fix overages by simplifying or extracting code, never by manual reformatting.
