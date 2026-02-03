#!/usr/bin/env python3
from __future__ import annotations

import logging
import sys
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
    "--minimal",
    is_flag=True,
    default=False,
    help="Run only audit + pyright + vulture; skip sonar and semantic gates.",
)
def main(**kwargs: object) -> None:
    """Entry point: load env, run skill, exit with its return code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    load_env_file(Path.cwd() / ".env")

    args = SimpleNamespace(**kwargs)
    raise SystemExit(run_skill(args))


if __name__ == "__main__":
    main()
