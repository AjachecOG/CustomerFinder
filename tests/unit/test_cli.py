"""CLI smoke tests."""

from __future__ import annotations

import importlib

import pytest
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


def test_calibration_help_lists_gui() -> None:
    result = runner.invoke(app, ["calibration", "--help"])
    assert result.exit_code == 0
    assert "gui" in result.stdout.lower()


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


def test_search_help_has_no_google_api_flags() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    help_text = result.stdout.lower()
    assert "--enrich" not in help_text
    assert "--google-max-requests" not in help_text
    assert "--strict" not in help_text
    assert "no api key" in help_text


def test_cli_rejects_removed_google_commands_and_flags() -> None:
    missing = runner.invoke(app, ["google-calibration", "--help"])
    assert missing.exit_code != 0
    root = runner.invoke(app, ["--help"])
    assert root.exit_code == 0
    assert "google-calibration" not in root.stdout.lower()
    rejected = runner.invoke(
        app,
        [
            "search",
            "--lat",
            "51.1079",
            "--lon",
            "17.0385",
            "--radius-km",
            "3",
            "--categories",
            "cafe",
            "--output",
            "out/x.csv",
            "--enrich",
            "google",
        ],
    )
    assert rejected.exit_code != 0


def test_google_places_module_is_absent() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("customer_finder.google_places")
