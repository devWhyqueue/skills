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
- `--scope AUTO` (default) reviews all changed Python files; `--scope <package>` restricts the run to that package
- Semantic checks are enabled by default; `--audit-only` generates semantic artifacts without gating, `--commit` gates on the filled ledger (disable with `--no-semantic`)

## How to run
Run via PowerShell using the skill’s local venv:

Audit only:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --audit-only`

Audit + autofix + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit`

Audit + autofix + commit (semantic gate disabled):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --no-semantic`

Restrict to a package (name or path):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --scope etl`

## Sonar configuration
- The calling project should provide `sonar-project.properties` (pysonar picks it up automatically).
- Put `SONAR_TOKEN` into the calling project’s `.env` (the runner loads it from the CWD).
- Optional overrides: pass `--sonar-host-url`, `--sonar-project-key`, `--sonar-sources`.
- PR-scoped gating: by default the skill evaluates only "new code" Quality Gate conditions (typically `new_*`) against `develop`. Override with `--sonar-gate-scope full` or `--sonar-reference-branch <branch>`.
- Sonar is enabled by default; disable with `--no-sonar`.

## Semantic gate
- Enabled by default for `--commit` runs (disable with `--no-semantic`).
- Enable explicitly with `--semantic` (useful when not running with `--commit`) to evaluate `SEMANTIC` rules from `clean_code_rules.yml`.
- The runner writes a deterministic scaffold ledger (`semantic_ledger.yml`) and a prompt (`semantic_prompt.md`) to a stable temp folder by default (or `--semantic-out-dir`).
- Codex (the agent) is expected to fill in `PASS|FAIL|NA` for each rule/file entry (use `NEEDS_HUMAN` only if truly undecidable) and rerun.
- If you only want artifacts (no gating), use `--semantic --semantic-scaffold-only`.

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
