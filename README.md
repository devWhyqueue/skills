# clean-code

Script-backed Codex skill to audit and clean up changed Python files on the current branch vs develop.

It enforces:
- your custom Clean Code Rules (see clean_code_rules.yml)
- ruff autofix + formatting
- SonarQube Quality Gate (via pysonar), new-code scoped by default

Also enforces (enabled by default):
- Semantic gate scaffold produces an index (`semantic_prompt.md` + `semantic_ledger.yml`) plus per-file ledgers/prompts under `ledgers/` and `prompts/`. It generates only one per-file ledger/prompt per run, and the index prompt shows one file at a time; rerun the skill to advance. It gates on the evaluated per-file ledgers (disable with `--no-semantic`).

## Run
Run via PowerShell using the skill’s local venv:

Restrict to a package (name or path):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --scope etl`

Audit + fix + gates + commit (default):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py"`

No commit:
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --no-commit`

Disable gates (still audits/fixes):
`& "$env:USERPROFILE\\.codex\\skills\\clean-code\\.venv\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --no-sonar --no-semantic`

Tip: if you pipe JSON output to a file, write it to a temp location (e.g. `Tee-Object -FilePath $env:TEMP\\clean-code.json`) to avoid creating untracked files in your repo.
