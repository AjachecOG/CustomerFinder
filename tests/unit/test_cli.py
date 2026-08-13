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


def test_overture_schema_command_with_mocked_stac() -> None:
    import httpx
    import respx

    from customer_finder.errors import ExitCode
    from customer_finder.overture import STAC_CATALOG_URL

    with respx.mock:
        respx.get(STAC_CATALOG_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "latest": "2026-07-22.0",
                    "links": [
                        {
                            "rel": "child",
                            "href": "./2026-07-22.0/catalog.json",
                            "latest": True,
                        }
                    ],
                },
            )
        )
        respx.get("https://stac.overturemaps.org/2026-07-22.0/catalog.json").mock(
            return_value=httpx.Response(
                200,
                json={"id": "2026-07-22.0", "schema:version": "1.18.0"},
            )
        )
        result = runner.invoke(app, ["overture", "schema", "--release", "latest"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "2026-07-22.0" in result.stdout
    assert "1.18.0" in result.stdout


def test_verbose_logging_does_not_enable_httpx_debug() -> None:
    import logging

    from customer_finder.cli import configure_logging

    configure_logging(verbose=True)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
    assert logging.getLogger("customer_finder").level == logging.DEBUG
