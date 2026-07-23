# skills

Personal skill collection.

## Layout

- `~/.codex/skills` is the canonical working tree.
- `~/.claude/skills` is a symlink to this directory, so Claude Code sees the same skills as Codex.
- Only `clean-code`, `doc-coauthoring`, `explain-diff-html`, `frontend-design`, `pdf`, `playwright`, and `review` are version-controlled here. Other top-level skill directories may exist locally for runtime use but are ignored by git.

## Skills

- `clean-code`: Python clean-code audit and gating pipeline.
- `doc-coauthoring`: Structured workflow for co-authoring documentation and specs.
- `explain-diff-html`: Generate a rich, interactive standalone HTML explanation of a code change, diff, branch, or PR.
- `frontend-design`: Production-grade frontend UI design with distinctive aesthetics.
- `pdf`: PDF processing guidance and helper scripts.
- `playwright`: Browser automation from the terminal via `playwright-cli`.
- `review`: Multi-axis code review guidance.

## Plugins

Recommended installs:

- [`caveman`](https://github.com/JuliusBrussee/caveman): compresses agent output (~65% fewer tokens) while keeping technical accuracy.
- [`ponytail`](https://github.com/DietrichGebert/ponytail): pushes a "lazy senior developer" / YAGNI discipline before generating code, favoring minimal diffs.
