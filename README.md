# skills

Personal skill collection.

## Layout

- `~/.codex/skills` is the canonical working tree.
- `~/.claude/skills` is a symlink to this directory, so Claude Code sees the same skills as Codex.
- Only `clean-code`, `doc-coauthoring`, and `explain-diff-html` are version-controlled here. Other top-level skill directories may exist locally for runtime use but are ignored by git.

## Skills

- `clean-code`: Python clean-code audit and gating pipeline.
- `doc-coauthoring`: Structured workflow for co-authoring documentation and specs.
- `explain-diff-html`: Generate a rich, interactive standalone HTML explanation of a code change, diff, branch, or PR.

## Plugins

Recommended installs:

- [`caveman`](https://github.com/JuliusBrussee/caveman): compresses agent output (~65% fewer tokens) while keeping technical accuracy.
- [`ponytail`](https://github.com/DietrichGebert/ponytail): pushes a "lazy senior developer" / YAGNI discipline before generating code, favoring minimal diffs.
- [`frontend-design`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design): official Anthropic plugin for production-grade frontend UI design with distinctive aesthetics. Install: `/plugin install frontend-design@claude-plugins-official`.
