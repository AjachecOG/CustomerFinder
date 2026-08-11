"""End-to-end offline pipeline against the Overture fixture."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from customer_finder.cli import app
from customer_finder.models import SearchRequest
from customer_finder.output import CSV_COLUMNS
from customer_finder.overture import local_fixture_path
from customer_finder.pipeline import run_search

runner = CliRunner()
EXPECTED = Path(__file__).resolve().parents[1] / "fixtures" / "expected_leads.csv"


def test_pipeline_fixture_matches_expected_csv(tmp_path: Path) -> None:
    output = tmp_path / "leads.csv"
    request = SearchRequest(
        lat=51.1079,
        lon=17.0385,
        radius_km=3,
        categories=["cafe", "bakery", "pastry", "ice_cream"],
        output_path=output,
        enrich="none",
        include_has_site=False,
        overture_release="fixture",
        overwrite=False,
    )
    result = run_search(request, parquet_path=str(local_fixture_path()))
    assert output.exists()
    assert output.with_name("leads.complete").exists()

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with EXPECTED.open(encoding="utf-8-sig", newline="") as handle:
        expected = list(csv.DictReader(handle))

    assert list(rows[0].keys()) == list(CSV_COLUMNS)
    assert [r["overture_id"] for r in rows] == [r["overture_id"] for r in expected]
    assert [r["score"] for r in rows] == [r["score"] for r in expected]
    assert [r["bucket"] for r in rows] == [r["bucket"] for r in expected]
    assert all(row["bucket"] != "has_owned_site" for row in rows)

    manifest = json.loads(output.with_name("leads.manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["output"] == len(rows)
    assert "api_key" not in json.dumps(manifest).lower()
    assert result.manifest["counts"]["deduplicated"] >= 1


def test_cli_search_with_fixture(tmp_path: Path) -> None:
    output = tmp_path / "cli_leads.csv"
    result = runner.invoke(
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
            "cafe,bakery,pastry,ice_cream",
            "--output",
            str(output),
            "--parquet",
            str(local_fixture_path()),
            "--overture-release",
            "fixture",
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "rows=" in result.stdout
