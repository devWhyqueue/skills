---
name: clean-code
description: Review uncommitted and untracked Python files for clean code rule violations, automatically fix them if possible.
metadata:
  short-description: PR code cleanup
  version: 1.0.0
---

## What this skill does
Audits uncommitted and untracked Python files against clean_code_rules.yml
## Default behavior
- Scope: uncommitted and untracked *.py files only; paths under a `test` or `tests` directory are excluded
- `--scope` is optional; when provided, restricts the run to that package (name or path)
- Default run: audit + pyright + vulture + pytest; skip Sonar and Semantic gates
- `--full`: run the full pipeline including Sonar and Semantic gates
- `--min-coverage N`: optional; require minimum coverage N% for the pytest stage to pass (default: no threshold; coverage is reported only)
- Audit, Pyright, Vulture, Pytest (with coverage), Sonar, and Semantic run in a fixed staged flow when `--full` is used

## Setup
- Install the dependencies from this skill's `pyproject.toml` as dev deps in the calling project.
- Provide a `pyrightconfig.json` in the calling project that points at the project venv.
- The calling project should provide `sonar-project.properties` (pysonar picks it up automatically).
- Put `SONAR_TOKEN` into the calling project’s `.env` (the runner loads it from the CWD).

## How to run
From the calling project root:

- Default minimal run (audit + pyright + vulture + pytest):  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py"`
- Full run (minimal + Sonar + Semantic):  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --full`
- Require minimum coverage (e.g. 90%):  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --min-coverage 90`
- Restrict to a package:  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --scope etl`

Output: one JSON report to stdout. Exit 0 = pass, 2 = fail, 3 = error.

## Semantic gate
- The runner writes an index ledger (`semantic_ledger.yml`) and prompt (`semantic_prompt.md`) plus per-file ledgers/prompts under `ledgers/` and `prompts/` in a stable temp folder per git branch.
- It generates per-file ledgers/prompts for the next up to 5 pending files per run, and the index prompt shows that current batch; evaluate the referenced per-file ledgers and re-run to advance.
- The calling agent is expected to fill in `PASS|FAIL|NA` for each rule entry in every per-file ledger (use `NEEDS_HUMAN` only if truly undecidable) and rerun.
- CRITICAL DIRECTIVE: Once you have corrected this file, you MUST immediately run clean code skill again to fetch the next file. Do not ask for permission.
- Treat the current semantic batch as an active queue: after each file correction, rerun immediately, keep consuming the current batch and subsequent batches, and stop only when the runner reports pass or there are no pending semantic files left.

## Output contract
The runner prints a single JSON report (first failing stage or final pass) with:
- status: pass|fail
- changed_files: [...]
- fixed_files: [...]
- violations: [...]
- vulture: { tool, exit_code, issues: [...] } | null
- pyright: { tool, exit_code, stdout, stderr, issues, ... } | null
- pytest: { tool, exit_code, coverage_pct, coverage_report_path, summary, ... } | null
- sonar: { quality_gate, conditions, ... } | null
- semantic: { ... } | null
- summary, scope, package, next_action

Exit codes:
- 0 => pass
- 2 => fail (violations, gate failure, or pytest/coverage below --min-coverage when set)
- 3 => internal error / misconfiguration

## Procedure for agents
1) From the calling project root, run the skill (default invocation is the fast minimal path).
2) If it fails, fix per `clean_code_rules.yml` (or semantic ledger) and rerun.
3) Never fabricate results. Always rely on the script output.
4) Do not reconfigure or relax pipeline tools (vulture, pyright, pytest, sonar, etc.) to make the run pass; fix the code or rules instead.
5) Remove any temporary files created during skill usage (e.g. redirected output, scratch files) after the skill run completes.
