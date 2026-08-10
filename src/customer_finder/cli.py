"""Typer CLI entrypoint for Customer Finder."""

from __future__ import annotations

import typer

from customer_finder import __version__

app = typer.Typer(
    name="finder",
    help="Find local cafes and bakeries likely without an owned website.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("version")
def version_cmd() -> None:
    """Print the installed package version and exit."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
