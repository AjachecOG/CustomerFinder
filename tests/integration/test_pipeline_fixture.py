"""End-to-end offline pipeline against the Overture fixture."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
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
    assert "google" not in manifest
    assert "google_place_id" not in rows[0]
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
    assert "bundle: manifest=" in result.stdout
    assert "verify_links=" in result.stdout
    assert "complete=" in result.stdout
    assert "data_fresh_until=" in result.stdout


def test_pipeline_never_calls_google_hosts_or_reads_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import urlparse

    import httpx

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "secret-google-key-should-not-be-read")
    seen_hosts: list[str] = []
    original_request = httpx.Client.request

    def guarded_request(
        self: httpx.Client,
        method: str,
        url: httpx.URL | str,
        *args: object,
        **kwargs: object,
    ) -> httpx.Response:
        host = (urlparse(str(url)).hostname or "").lower()
        seen_hosts.append(host)
        if host == "google.com" or host.endswith(".google.com") or host.endswith("googleapis.com"):
            raise AssertionError(f"standard pipeline requested Google host {host}")
        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "request", guarded_request)

    output = tmp_path / "leads.csv"
    request = SearchRequest(
        lat=51.1079,
        lon=17.0385,
        radius_km=3,
        categories=["cafe", "bakery", "pastry", "ice_cream"],
        output_path=output,
        overture_release="fixture",
    )
    result = run_search(request, parquet_path=str(local_fixture_path()))
    dumped = json.dumps(result.manifest)
    assert "secret-google-key-should-not-be-read" not in dumped
    assert "google" not in result.manifest
    assert "GOOGLE_MAPS_API_KEY" not in dumped
    assert all(
        host != "google.com"
        and not host.endswith(".google.com")
        and not host.endswith("googleapis.com")
        for host in seen_hosts
    )
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "google_place_id" not in rows[0]
    links = output.with_name("leads.verify_links.txt").read_text(encoding="utf-8")
    assert "https://www.google.com/maps/search/" in links


def test_unexpected_pipeline_error_exposes_run_id_not_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from customer_finder.errors import CustomerFinderError

    output = tmp_path / "leads.csv"
    request = SearchRequest(
        lat=51.1079,
        lon=17.0385,
        radius_km=3,
        categories=["cafe"],
        output_path=output,
        overture_release="fixture",
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("GOOGLE_MAPS_API_KEY=secret-should-not-leak")

    monkeypatch.setattr("customer_finder.pipeline.fetch_places", boom)
    with pytest.raises(CustomerFinderError) as exc:
        run_search(request, parquet_path=str(local_fixture_path()))
    assert "run_id=" in exc.value.message
    assert "secret-should-not-leak" not in exc.value.message
    failed = json.loads(output.with_name("leads.failed.manifest.json").read_text(encoding="utf-8"))
    assert "secret-should-not-leak" not in json.dumps(failed)
    assert failed["error"]["type"] == "RuntimeError"
    assert failed["error"]["run_id"]
