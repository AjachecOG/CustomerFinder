"""Typer CLI entrypoint for Customer Finder."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from customer_finder import __version__
from customer_finder.errors import ConfigError, CustomerFinderError, ExitCode
from customer_finder.settings import load_config

app = typer.Typer(
    name="finder",
    help="Find local cafes and bakeries likely without an owned website.",
    no_args_is_help=True,
    add_completion=False,
)

config_app = typer.Typer(
    name="config",
    help="Validate built-in or override YAML configuration.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(config_app, name="config")


@app.command("version")
def version_cmd() -> None:
    """Print the installed package version and exit."""
    typer.echo(__version__)


@config_app.command("validate")
def config_validate_cmd(
    config_dir: Annotated[
        Path | None,
        typer.Option(
            "--config-dir",
            help="Directory with the complete four-file YAML set (no mixing).",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Load and validate categories, domain rules, denylist, and taxonomy snapshot."""
    try:
        cfg = load_config(config_dir)
    except ConfigError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=ExitCode.CONFIG) from exc
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc

    source = "built-in package config" if cfg.source_dir is None else str(cfg.source_dir)
    typer.echo(f"OK: configuration valid ({source})")
    typer.echo(f"schema_version={cfg.taxonomy_snapshot.schema_version}")
    typer.echo(f"categories={','.join(cfg.category_aliases())}")


if __name__ == "__main__":
    app()
