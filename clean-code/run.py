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
    "--full",
    is_flag=True,
    default=False,
    help=(
        "Extend the default pipeline with Sonar and Semantic gates "
        "(default without this flag: audit + pyright + vulture + pytest only)."
    ),
)
@click.option(
    "--min-coverage",
    type=int,
    default=None,
    help="Require this minimum coverage %% for pytest to pass (default: report only, no threshold).",
)
@click.option(
    "--vulture-scope",
    default="",
    show_default=False,
    help=(
        "Optional comma-separated paths for Vulture scan roots. "
        "When set, Vulture scans these paths instead of the default root/src."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Print the complete machine-readable report instead of concise text.",
)
def main(**kwargs: object) -> None:
    """Entry point: load env, run skill, exit with its return code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    load_env_file(Path.cwd() / ".env")

    args = SimpleNamespace(**kwargs)
    raise SystemExit(run_skill(args))


if __name__ == "__main__":
    main()
