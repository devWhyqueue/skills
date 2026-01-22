---
name: clean-code-pr-review
description: Review all changed Python files on the current branch vs develop for clean code rule violations, automatically fix them, run SonarQube quality gate via pysonar, and create a single conventional refactor commit.
metadata:
  short-description: PR clean code review + autofix + Sonar gate + single refactor commit
  version: 1.0.0
---

## What this skill does
- Computes the diff between the current branch and develop
- Audits changed Python files against clean_code_rules.md
- Auto-fixes safe mechanical issues (ruff fix/format, unused imports, simple print->logging)
- Re-audits until clean or remaining violations require semantic refactor
- Runs SonarQube via pysonar and enforces Quality Gate only
- Produces ONE conventional commit: refactor(<scope>): clean code compliance

## Default behavior
- Base branch: develop (fallback: origin/develop)
- Only checks changed *.py files
- Requires clean working tree (to guarantee exactly one refactor commit)
- Commit scope is AUTO-derived from changed files (can be overridden)

## How to run
Run via PowerShell using the skill’s local venv:

Audit only:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --audit-only`

Audit + autofix + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --commit`

Audit + autofix + Sonar gate + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --commit --sonar`

Override scope:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --commit --scope etl`

## Output contract
The runner prints JSON with:
- status: pass|fail
- changed_files: [...]
- fixed_files: [...]
- violations: [...]
- sonar: { quality_gate, conditions, ... } | null
- commit: { attempted, created, message }
- summary, scope, next_action

Exit codes:
- 0 => pass
- 2 => fail (violations or sonar gate failure)
- 3 => internal error / misconfiguration

## Procedure for Codex
1) Run with --commit --sonar.
2) If it fails with remaining violations, fix them per clean_code_rules.md and rerun.
3) When status=pass, ensure the single refactor commit exists.
4) Never fabricate results. Always rely on the script output.
