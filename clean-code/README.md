# clean-code

Script-backed skill to audit and clean up uncommitted and untracked Python files. Scope is uncommitted/untracked *.py only.

It enforces:
- your custom Clean Code Rules (see clean_code_rules.yml)
- ruff autofix + formatting
- vulture dead-code checks
- pyright type checks
- SonarQube Quality Gate (via pysonar), new-code scoped by default
- Semantic gate scaffold produces an index (`semantic_prompt.md` + `semantic_ledger.yml`) plus per-file ledgers/prompts under `ledgers/` and `prompts/`. It generates the next up to 5 pending per-file ledgers/prompts per run, and the index prompt shows that batch; rerun the skill to advance through the queue. It gates on the evaluated per-file ledgers.

Setup notes:
- Install the dependencies from this skill's `pyproject.toml` as dev deps in the calling project.
- Provide a `pyrightconfig.json` in the calling project that points at the project venv.

## Run
From the calling project’s venv:

Audit + fix + gates (default):
`uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py"`

Minimal run (audit + pyright + vulture + pytest; no Sonar/Semantic):
`uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --minimal`

Restrict to a package (name or path):
`uv run python "$env:USERPROFILE\.codex\skills\clean-code\run.py" --scope etl`

Tip: if you pipe JSON output to a file, write it to a temp location (e.g. `Tee-Object -FilePath $env:TEMP\\clean-code.json`) to avoid creating untracked files in your repo.
