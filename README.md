# skills

User-defined Codex skills tracked in `git@github.com:devWhyqueue/skills.git`.

## Layout

- `/mnt/c/Users/Yannik/.codex/skills` is the canonical working tree.
- `/home/yannik/.codex/skills` is a symlink to the Windows path so WSL and Windows use the same files.
- Only `clean-code` and `pdf` are version-controlled here. Other top-level skill directories may exist locally for runtime use but are ignored by git.

## Skills

- `clean-code`: Python clean-code audit and gating pipeline.
- `pdf`: PDF processing guidance and helper scripts.

## Workflow

Work from either path, but treat the Windows-backed directory as the source of truth. `git status` from WSL and Windows should reflect the same repository state.
