from __future__ import annotations

from click.testing import CliRunner

import run as run_mod


def test_help_shows_full_and_not_minimal() -> None:
    result = CliRunner().invoke(run_mod.main, ["--help"])
    assert result.exit_code == 0
    assert "--full" in result.output
    assert "--minimal" not in result.output


def test_default_invocation_passes_full_false(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_load_env_file(path) -> None:
        observed["env_path"] = path

    def _fake_run_skill(args) -> int:
        observed["full"] = args.full
        observed["scope"] = args.scope
        observed["min_coverage"] = args.min_coverage
        return 0

    monkeypatch.setattr(run_mod, "load_env_file", _fake_load_env_file)
    monkeypatch.setattr(run_mod, "run_skill", _fake_run_skill)

    result = CliRunner().invoke(run_mod.main, [])

    assert result.exit_code == 0
    assert observed["full"] is False
    assert observed["scope"] == ""
    assert observed["min_coverage"] is None


def test_full_flag_passes_full_true(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_run_skill(args) -> int:
        observed["full"] = args.full
        return 0

    monkeypatch.setattr(run_mod, "load_env_file", lambda path: None)
    monkeypatch.setattr(run_mod, "run_skill", _fake_run_skill)

    result = CliRunner().invoke(run_mod.main, ["--full"])

    assert result.exit_code == 0
    assert observed["full"] is True
