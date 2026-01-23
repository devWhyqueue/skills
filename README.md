# clean-code

Script-backed Codex skill to audit and clean up changed Python files on the current branch vs develop.

It enforces:
- your custom Clean Code Rules (see clean_code_rules.yml)
- ruff autofix + formatting
- SonarQube Quality Gate (via pysonar), PR-scoped by default (new code only)

Also enforces (enabled by default):
- Semantic gate scaffold produces `semantic_prompt.md` + `semantic_ledger.yml` for Codex/human review; it gates on the filled ledger for `--commit` runs (disable with `--no-semantic`).

## Run
Run via PowerShell using the skill’s local venv:

Audit only:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --audit-only`

Restrict to a package (name or path):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --scope etl`

Audit + fix + commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit`

Audit + fix + commit (semantic gate disabled):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --no-semantic`

PR-scoped Sonar gate (default, new code vs develop):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --sonar-gate-scope new-code --sonar-reference-branch develop`

Full Sonar Quality Gate (includes global conditions):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --commit --sonar-gate-scope full`

Tip: if you pipe JSON output to a file, write it to a temp location (e.g. `Tee-Object -FilePath $env:TEMP\\clean-code.json`) to avoid creating untracked files in your repo.
