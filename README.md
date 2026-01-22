# clean-code-pr-review

Script-backed Codex skill to audit and clean up changed Python files on the current branch vs develop.

It enforces:
- your custom Clean Code Rules (see clean_code_rules.md)
- ruff autofix + formatting
- SonarQube Quality Gate (via pysonar)

## Run
Run via PowerShell using the skill’s local venv:

Audit only:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --audit-only`

Audit + fix + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --commit`

Audit + fix + Sonar gate + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code-pr-review\\run.py" --commit --sonar`
