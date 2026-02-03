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
- `--minimal`: run only audit + pyright + vulture; skip Sonar and Semantic gates
- Audit, Pyright, Sonar, and Semantic run in a fixed staged flow (unless `--minimal`)

## Setup
- Install the dependencies from this skill's `pyproject.toml` as dev deps in the calling project.
- Provide a `pyrightconfig.json` in the calling project that points at the project venv.
- The calling project should provide `sonar-project.properties` (pysonar picks it up automatically).
- Put `SONAR_TOKEN` into the calling project’s `.env` (the runner loads it from the CWD).

## How to run
From the calling project root:

- Default (audit + autofix + gates):  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py"`
- Minimal (audit + pyright + vulture only):  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --minimal`
- Restrict to a package:  
  `uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --scope etl`

Output: one JSON report to stdout. Exit 0 = pass, 2 = fail, 3 = error.

## Semantic gate
- The runner writes an index ledger (`semantic_ledger.yml`) and prompt (`semantic_prompt.md`) plus per-file ledgers/prompts under `ledgers/` and `prompts/` in a stable temp folder per git branch.
- It generates only one per-file ledger/prompt per run, and the index prompt shows one file at a time; evaluate the referenced per-file ledger and re-run to advance.
- The calling agent is expected to fill in `PASS|FAIL|NA` for each rule entry in every per-file ledger (use `NEEDS_HUMAN` only if truly undecidable) and rerun.

## Output contract
The runner prints a single JSON report (first failing stage or final pass) with:
- status: pass|fail
- changed_files: [...]
- fixed_files: [...]
- violations: [...]
- vulture: { tool, exit_code, issues: [...] } | null
- pyright: { tool, exit_code, stdout, stderr, issues, ... } | null
- sonar: { quality_gate, conditions, ... } | null
- semantic: { ... } | null
- summary, scope, package, next_action

Exit codes:
- 0 => pass
- 2 => fail (violations or sonar gate failure)
- 3 => internal error / misconfiguration

## Procedure for agents
1) From the calling project root, run the skill (use `--minimal` for fast iteration).
2) If it fails, fix per `clean_code_rules.yml` (or semantic ledger) and rerun.
3) Never fabricate results. Always rely on the script output.
4) Do not reconfigure or relax pipeline tools (vulture, pyright, sonar, etc.) to make the run pass; fix the code or rules instead.
5) Remove any temporary files created during skill usage (e.g. redirected output, scratch files) after the skill run completes.
