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
- Auto-fixes safe mechanical issues (ruff fix/format, unused imports, simple print->logging)
- Re-audits until clean or remaining violations require semantic refactor
- Runs SonarQube via pysonar and enforces Quality Gate only
- Produces ONE conventional commit: refactor(<scope>): clean code compliance

## Default behavior
- Base branch: develop (fallback: origin/develop)
- Only checks changed *.py files
- Requires a clean working tree, or only pre-existing changes limited to the PR-changed Python files (to guarantee exactly one refactor commit)
- `--scope` is optional; when provided, restricts the run to that package (name or path)
- Audit, Sonar, and Semantic are enabled by default (disable with `--no-audit`, `--no-sonar`, `--no-semantic`)
- Commit-on-pass is enabled by default (disable with `--no-commit`)

## How to run
Run via PowerShell using the skill’s local venv:

Audit + autofix + gates + commit (default):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py"`

No commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --no-commit`

Restrict to a package (name or path):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --scope etl`

## Sonar configuration
- The calling project should provide `sonar-project.properties` (pysonar picks it up automatically).
- Put `SONAR_TOKEN` into the calling project’s `.env` (the runner loads it from the CWD).
- The skill enforces the "new-code" gate against `develop`.

## Semantic gate
- Enabled by default (disable with `--no-semantic`).
- The runner writes an index ledger (`semantic_ledger.yml`) and prompt (`semantic_prompt.md`) plus per-file ledgers/prompts under `ledgers/` and `prompts/` in a stable temp folder per git branch.
- The index prompt shows one file at a time; evaluate the referenced per-file ledger and re-run to advance.
- The calling agent is expected to fill in `PASS|FAIL|NA` for each rule entry in every per-file ledger (use `NEEDS_HUMAN` only if truly undecidable) and rerun.

## Output contract
The runner prints JSON with:
- status: pass|fail
- changed_files: [...]
- fixed_files: [...]
- violations: [...]
- sonar: { quality_gate, conditions, ... } | null
- commit: { attempted, created, message }
- summary, scope, package, next_action

Exit codes:
- 0 => pass
- 2 => fail (violations or sonar gate failure)
- 3 => internal error / misconfiguration

## Procedure for Codex
1) Run with `--commit` (Sonar runs by default).
2) If it fails with remaining violations, fix them per `clean_code_rules.yml` and rerun (it will tolerate a dirty tree only if the changes are limited to the PR-changed Python files).
3) When status=pass, ensure the single refactor commit exists.
4) Never fabricate results. Always rely on the script output.
