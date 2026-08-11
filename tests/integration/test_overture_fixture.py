"""Offline integration tests against the Overture parquet fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from customer_finder.errors import OvertureError
from customer_finder.geometry import compute_bbox
from customer_finder.overture import (
    category_codes_for_aliases,
    check_schema,
    connect_duckdb,
    fetch_places,
    local_fixture_path,
    map_overture_row,
    query_category_bbox,
)
from customer_finder.settings import load_builtin_config

CENTER_LAT = 51.1079
CENTER_LON = 17.0385
RADIUS_KM = 3.0
FIXTURE = local_fixture_path()


@pytest.fixture(scope="module")
def con():
    connection = connect_duckdb()
    yield connection
    connection.close()


def test_fixture_exists() -> None:
    assert FIXTURE.is_file(), f"Missing fixture at {FIXTURE}"


def test_schema_check_passes_on_fixture(con) -> None:
    check_schema(con, str(FIXTURE), release_id="fixture")


def test_schema_check_fails_on_missing_column(con, tmp_path: Path) -> None:
    bad = tmp_path / "bad.parquet"
    con.execute(f"COPY (SELECT 'x' AS id, 1 AS version) TO '{bad}' (FORMAT PARQUET)")
    with pytest.raises(OvertureError) as exc:
        check_schema(con, str(bad), release_id="fixture")
    assert "missing columns" in exc.value.message
    assert "fixture" in exc.value.message


def test_query_excludes_outside_bbox_includes_boundary_cardinals(con) -> None:
    cfg = load_builtin_config()
    basic, taxonomy = category_codes_for_aliases(["cafe", "bakery", "pastry", "ice_cream"], cfg)
    bbox = compute_bbox(CENTER_LAT, CENTER_LON, RADIUS_KM)
    rows, stats = query_category_bbox(
        con,
        str(FIXTURE),
        bbox,
        basic_codes=basic,
        taxonomy_codes=taxonomy,
        release_id="fixture",
    )
    ids = {r["id"] for r in rows}
    assert "place_outside_bbox" not in ids
    assert "place_bbox_only" in ids
    assert stats.raw_category_bbox == len(rows)
    assert stats.raw_category_bbox > 0


def test_radius_filter_drops_bbox_only_point(con) -> None:
    cfg = load_builtin_config()
    filtered, stats = fetch_places(
        parquet_path=str(FIXTURE),
        center_lat=CENTER_LAT,
        center_lon=CENTER_LON,
        radius_km=RADIUS_KM,
        aliases=["cafe", "bakery", "pastry", "ice_cream"],
        config=cfg,
        release_id="fixture",
        con=con,
    )
    ids = {place.overture_id for place, _ in filtered}
    assert "place_bbox_only" not in ids
    assert "place_outside_bbox" not in ids
    assert "place_nosite" in ids
    assert "place_owned" in ids
    assert stats.after_radius == len(filtered)
    assert stats.after_radius < stats.raw_category_bbox


def test_mapping_deterministic_and_complete(con) -> None:
    cfg = load_builtin_config()
    basic, taxonomy = category_codes_for_aliases(["cafe"], cfg)
    bbox = compute_bbox(CENTER_LAT, CENTER_LON, RADIUS_KM)
    rows, _ = query_category_bbox(
        con,
        str(FIXTURE),
        bbox,
        basic_codes=basic,
        taxonomy_codes=taxonomy,
        release_id="fixture",
    )
    places_a = [map_overture_row(r) for r in rows]
    places_b = [map_overture_row(r) for r in rows]
    assert [p.model_dump() for p in places_a] == [p.model_dump() for p in places_b]
    owned = next(p for p in places_a if p.overture_id == "place_owned")
    assert owned.websites == ["https://cafewlasna.pl"]
    assert owned.name == "Cafe Wlasna"
    chain = next(p for p in places_a if p.overture_id == "place_chain")
    assert chain.brand_name == "Starbucks"


def test_fetch_places_result_order_stable(con) -> None:
    cfg = load_builtin_config()
    a, _ = fetch_places(
        parquet_path=str(FIXTURE),
        center_lat=CENTER_LAT,
        center_lon=CENTER_LON,
        radius_km=RADIUS_KM,
        aliases=["cafe"],
        config=cfg,
        release_id="fixture",
        con=con,
    )
    b, _ = fetch_places(
        parquet_path=str(FIXTURE),
        center_lat=CENTER_LAT,
        center_lon=CENTER_LON,
        radius_km=RADIUS_KM,
        aliases=["cafe"],
        config=cfg,
        release_id="fixture",
        con=con,
    )
    assert [p.overture_id for p, _ in a] == [p.overture_id for p, _ in b]
