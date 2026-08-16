"""Typer CLI entrypoint for Customer Finder."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from customer_finder import __version__
from customer_finder.calibration import (
    evaluate_calibration,
    prepare_calibration,
)
from customer_finder.calibration_gui import GuiSession, serve_gui
from customer_finder.errors import (
    ArgumentError,
    ConfigError,
    CustomerFinderError,
    ExitCode,
)
from customer_finder.models import SearchRequest
from customer_finder.output import stale_output_warning
from customer_finder.overture import (
    assert_schema_matches_snapshot,
    connect_duckdb,
    resolve_release,
)
from customer_finder.pipeline import run_search
from customer_finder.settings import load_config

app = typer.Typer(
    name="finder",
    help=(
        "Find local cafes and bakeries likely without an owned website. "
        "Overture-only; no commercial API key required."
    ),
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

overture_app = typer.Typer(
    name="overture",
    help="Overture Maps diagnostics.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(overture_app, name="overture")

calibration_app = typer.Typer(
    name="calibration",
    help="Prepare and evaluate manual calibration reviews.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(calibration_app, name="calibration")


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


@overture_app.command("schema")
def overture_schema_cmd(
    release: Annotated[
        str,
        typer.Option("--release", help="Overture release id or 'latest'."),
    ] = "latest",
    config_dir: Annotated[
        Path | None,
        typer.Option(
            "--config-dir",
            help="Optional complete YAML override directory.",
            exists=False,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Resolve a release via STAC and compare schema:version to the taxonomy snapshot."""
    try:
        cfg = load_config(config_dir)
        resolved = resolve_release(
            release,
            snapshot_schema_version=cfg.taxonomy_snapshot.schema_version,
        )
        assert_schema_matches_snapshot(resolved, cfg)
        con = connect_duckdb()
        con.close()
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc

    typer.echo(f"OK: release={resolved.release_id}")
    typer.echo(f"schema_version={resolved.schema_version}")
    typer.echo(f"parquet={resolved.parquet_glob}")
    typer.echo(f"snapshot_schema_version={cfg.taxonomy_snapshot.schema_version}")
    for warning in resolved.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)


def configure_logging(*, verbose: bool) -> None:
    """Log to stderr. Never enable httpx/httpcore DEBUG (headers can include API keys)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("customer_finder").setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@app.command("search")
def search_cmd(
    lat: Annotated[float, typer.Option("--lat", help="Center latitude (Poland MVP).")],
    lon: Annotated[float, typer.Option("--lon", help="Center longitude (Poland MVP).")],
    radius_km: Annotated[float, typer.Option("--radius-km", help="Search radius in km.")],
    categories: Annotated[
        str,
        typer.Option("--categories", help="Comma-separated category aliases."),
    ],
    output: Annotated[Path, typer.Option("--output", help="Output CSV path.")],
    min_score: Annotated[int, typer.Option("--min-score")] = 0,
    top: Annotated[int | None, typer.Option("--top")] = None,
    include_has_site: Annotated[bool, typer.Option("--include-has-site")] = False,
    overture_release: Annotated[str, typer.Option("--overture-release")] = "latest",
    config_dir: Annotated[Path | None, typer.Option("--config-dir")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    parquet: Annotated[
        Path | None,
        typer.Option(
            "--parquet",
            help="Offline GeoParquet path (tests / fixtures). Skips STAC/S3.",
            exists=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Search Overture Places; write CSV, manifest, and verify links. No API key required."""
    configure_logging(verbose=verbose)
    try:
        request = SearchRequest.model_validate(
            {
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "categories": categories,
                "output_path": output,
                "min_score": min_score,
                "top": top,
                "include_has_site": include_has_site,
                "overture_release": overture_release,
                "config_dir": config_dir,
                "overwrite": overwrite,
            }
        )
    except ValidationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=ExitCode.BAD_ARGS) from exc
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=ExitCode.BAD_ARGS) from exc

    parquet_path = str(parquet) if parquet is not None else None
    try:
        result = run_search(request, parquet_path=parquet_path)
    except ArgumentError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception:
        typer.secho(
            "Unexpected error (run_id unknown; see failed manifest if present)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=ExitCode.UNEXPECTED) from None

    counts = result.manifest["counts"]
    typer.echo(
        f"Wrote {result.output_paths.csv_path} "
        f"(rows={counts.get('output', 0)}, release={result.manifest['overture_release']})"
    )
    typer.echo(
        "bundle: "
        f"manifest={result.output_paths.manifest_path}, "
        f"verify_links={result.output_paths.verify_links_path}, "
        f"complete={result.output_paths.complete_path}"
    )
    typer.echo(f"data_fresh_until={result.manifest['data_fresh_until']}")
    typer.echo("counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    for warning in result.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)


@calibration_app.command("prepare")
def calibration_prepare_cmd(
    leads: Annotated[Path, typer.Option("--leads", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    limit: Annotated[int, typer.Option("--limit")] = 30,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Create an empty calibration CSV from top leads for human review."""
    try:
        stale = stale_output_warning(leads)
        path = prepare_calibration(leads, output, limit=limit, overwrite=overwrite)
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    if stale:
        typer.secho(f"warning: {stale}", fg=typer.colors.YELLOW, err=True)
    typer.echo(f"Wrote {path} (limit={limit}). Fill the five review fields manually.")


@calibration_app.command("evaluate")
def calibration_evaluate_cmd(
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Evaluate a human-reviewed calibration CSV and optionally write approval."""
    try:
        summary = evaluate_calibration(file, output)
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    typer.echo(json.dumps({"passed": summary["passed"], "top20": summary["top20"]}, indent=2))
    if summary.get("approved_path"):
        typer.echo(f"approved={summary['approved_path']}")


@calibration_app.command("gui")
def calibration_gui_cmd(
    leads: Annotated[
        Path | None,
        typer.Option("--leads", help="Leads CSV path used for search/prepare."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Calibration CSV written by the review desk."),
    ] = None,
    summary: Annotated[
        Path | None,
        typer.Option("--summary", help="Evaluate summary JSON path."),
    ] = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser"),
    ] = True,
    parquet: Annotated[
        Path | None,
        typer.Option(
            "--parquet",
            help="Optional offline GeoParquet (skips live Overture).",
            exists=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    overture_release: Annotated[
        str,
        typer.Option(
            "--overture-release",
            help="Overture release for GUI searches (latest or YYYY-MM-DD.N).",
        ),
    ] = "latest",
    limit: Annotated[int, typer.Option("--limit")] = 30,
) -> None:
    """Open a localhost review desk for Milestone 5 calibration."""
    session = GuiSession(
        leads_csv=leads or Path("out/leads_wroclaw.csv"),
        calibration_csv=output or Path("out/calibration.csv"),
        summary_path=summary or Path("out/calibration.summary.json"),
        overture_release=overture_release,
        parquet_path=parquet,
        limit=limit,
    )
    typer.echo(f"Calibration GUI: http://127.0.0.1:{port}/")
    try:
        serve_gui(session, host=host, port=port, open_browser=open_browser)
    except CustomerFinderError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc


if __name__ == "__main__":
    app()
