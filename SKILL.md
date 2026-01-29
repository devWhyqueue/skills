---
name: clean-code
description: Review all changed Python files on the current branch vs develop for clean code rule violations, automatically fix them if possible, and create a single conventional refactor commit.
metadata:
  short-description: PR code cleanup
  version: 1.0.0
---

## What this skill does
- Computes the diff between the current branch and develop
- Audits changed Python files against clean_code_rules.yml
- Produces ONE conventional commit: refactor(<scope>): clean code compliance

## Default behavior
- Base branch: develop (fallback: origin/develop)
- Only checks changed *.py files
- Requires a clean working tree, or only pre-existing changes limited to the PR-changed Python files (to guarantee exactly one refactor commit)
- `--scope` is optional; when provided, restricts the run to that package (name or path)
- Audit, Pyright, Sonar, and Semantic run in a fixed staged flow
- Commit-on-pass is always enabled

## Setup
- Install the dependencies from this skill's `pyproject.toml` as dev deps in the calling project.
- Provide a `pyrightconfig.json` in the calling project that points at the project venv.
- The calling project should provide `sonar-project.properties` (pysonar picks it up automatically).
- Put `SONAR_TOKEN` into the calling project’s `.env` (the runner loads it from the CWD).

## How to run
Run via PowerShell using the calling project’s venv:

Audit + autofix + gates + commit (default):
`& "$env:VIRTUAL_ENV\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py"`

Restrict to a package (name or path):
`& "$env:VIRTUAL_ENV\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --scope etl`

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
- pyright: { tool, exit_code, stdout, stderr, issues, ... } | null
- sonar: { quality_gate, conditions, ... } | null
- semantic: { ... } | null
- commit: { attempted, created, message }
- summary, scope, package, next_action

Exit codes:
- 0 => pass
- 2 => fail (violations or sonar gate failure)
- 3 => internal error / misconfiguration

## Procedure for Codex
1) Run `run.py` (stages: audit-only -> audit+pyright -> audit+pyright+sonar -> audit+pyright+sonar+semantic).
2) If it fails, fix per `clean_code_rules.yml` (or semantic ledger) and rerun. It tolerates a dirty tree only if changes are limited to the PR-changed Python files.
3) When status=pass, ensure the single refactor commit exists.
4) Never fabricate results. Always rely on the script output.
