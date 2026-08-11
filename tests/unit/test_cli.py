"""CLI smoke tests."""

from __future__ import annotations

from typer.testing import CliRunner

from customer_finder import __version__
from customer_finder.cli import app

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_cli_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "finder" in result.stdout.lower()


def test_config_help_lists_validate() -> None:
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "validate" in result.stdout.lower()
