#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import click

from cli.env import load_env_file
from cli.runner import run as run_skill


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--scope",
    default="",
    show_default=False,
    help="Optional package to target (name or path). Default: all changed Python files.",
)
@click.option(
    "--audit/--no-audit",
    default=True,
    show_default=True,
    help="Run clean-code audit + autofix.",
)
@click.option(
    "--sonar/--no-sonar",
    default=True,
    show_default=True,
    help="Run SonarQube Quality Gate.",
)
@click.option(
    "--semantic/--no-semantic",
    default=True,
    show_default=True,
    help="Run semantic gate (ledger-based).",
)
@click.option(
    "--commit/--no-commit",
    default=True,
    show_default=True,
    help="Create a refactor commit on pass.",
)
def main(**kwargs: object) -> None:
    load_env_file(Path.cwd() / ".env")

    args = SimpleNamespace(**kwargs)
    raise SystemExit(run_skill(args))


if __name__ == "__main__":
    main()
