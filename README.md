# clean-code

Script-backed Codex skill to audit and clean up changed Python files on the current branch vs develop.

It enforces:
- your custom Clean Code Rules (see clean_code_rules.yml)
- ruff autofix + formatting
- pyright type checks
- SonarQube Quality Gate (via pysonar), new-code scoped by default
- Semantic gate scaffold produces an index (`semantic_prompt.md` + `semantic_ledger.yml`) plus per-file ledgers/prompts under `ledgers/` and `prompts/`. It generates only one per-file ledger/prompt per run, and the index prompt shows one file at a time; rerun the skill to advance. It gates on the evaluated per-file ledgers.

## Run
Run via PowerShell using the calling project’s venv:

Restrict to a package (name or path):
`& "$env:VIRTUAL_ENV\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py" --scope etl`

Audit + fix + gates + commit (default):
`& "$env:VIRTUAL_ENV\\Scripts\\python.exe" "$env:USERPROFILE\\.codex\\skills\\clean-code\\run.py"`

Tip: if you pipe JSON output to a file, write it to a temp location (e.g. `Tee-Object -FilePath $env:TEMP\\clean-code.json`) to avoid creating untracked files in your repo.
