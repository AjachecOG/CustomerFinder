"""Unit tests for Overture STAC resolution and SQL helpers."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from customer_finder.errors import ConfigError, OvertureError
from customer_finder.overture import (
    STAC_CATALOG_URL,
    assert_schema_matches_snapshot,
    build_category_sql,
    map_overture_row,
    resolve_release,
)
from customer_finder.settings import load_builtin_config, validate_category_aliases


@respx.mock
def test_resolve_latest_release_reads_schema_version() -> None:
    respx.get(STAC_CATALOG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "latest": "2026-07-22.0",
                "links": [
                    {
                        "rel": "child",
                        "href": "./2026-07-22.0/catalog.json",
                        "title": "Latest",
                        "latest": True,
                    }
                ],
            },
        )
    )
    child_url = "https://stac.overturemaps.org/2026-07-22.0/catalog.json"
    respx.get(child_url).mock(
        return_value=httpx.Response(
            200,
            json={"id": "2026-07-22.0", "schema:version": "v1.18.0"},
        )
    )
    resolved = resolve_release("latest")
    assert resolved.release_id == "2026-07-22.0"
    assert resolved.schema_version == "1.18.0"
    assert "2026-07-22.0" in resolved.parquet_glob


@respx.mock
def test_resolve_latest_rejects_missing_schema_version() -> None:
    respx.get(STAC_CATALOG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "latest": "2026-07-22.0",
                "links": [{"rel": "child", "href": "./2026-07-22.0/catalog.json", "latest": True}],
            },
        )
    )
    respx.get("https://stac.overturemaps.org/2026-07-22.0/catalog.json").mock(
        return_value=httpx.Response(
            200,
            json={"id": "2026-07-22.0", "schema:version": None},
        )
    )
    with pytest.raises(OvertureError) as exc:
        resolve_release("latest")
    assert "schema:version" in exc.value.message


def test_assert_schema_mismatch() -> None:
    cfg = load_builtin_config()
    from customer_finder.overture import ResolvedRelease

    resolved = ResolvedRelease(
        release_id="2026-07-22.0",
        schema_version="9.9.9",
        parquet_glob="s3://x",
        catalog_url="https://example.test",
    )
    with pytest.raises(OvertureError):
        assert_schema_matches_snapshot(resolved, cfg)


def test_sql_injection_alias_rejected_before_query() -> None:
    cfg = load_builtin_config()
    with pytest.raises(ConfigError):
        validate_category_aliases(["cafe'; DROP TABLE places;--"], cfg)


def test_build_category_sql_uses_placeholders_only() -> None:
    sql, params = build_category_sql(["cafe"], ["bakery", "cafe"])
    assert "?" in sql
    assert "bakery" not in sql
    assert "cafe" not in sql.replace("basic_category", "").replace("taxonomy", "")
    assert params == ["cafe", "bakery", "cafe", "bakery", "cafe", "bakery", "cafe"]


def test_map_overture_row_prefers_pl_address_and_primary_name() -> None:
    row = {
        "id": "abc",
        "version": 2,
        "names": {"primary": "Piekarnia Test"},
        "basic_category": None,
        "taxonomy": {
            "primary": "bakery",
            "hierarchy": ["food_and_drink", "bakery"],
            "alternates": [],
        },
        "confidence": 0.5,
        "operating_status": "open",
        "websites": None,
        "socials": ["https://instagram.com/x"],
        "emails": [],
        "phones": ["+48111"],
        "brand": {"names": {"primary": "BrandX"}},
        "addresses": [
            {
                "freeform": "DE street",
                "locality": "Berlin",
                "postcode": "10115",
                "country": "DE",
            },
            {
                "freeform": "ul. Polska 1",
                "locality": "Wrocław",
                "postcode": "50-001",
                "country": "PL",
            },
        ],
        "sources": [
            {
                "dataset": "meta",
                "license": "ODbL",
                "property": "/properties/names",
                "update_time": "2026-01-01T00:00:00Z",
            }
        ],
        "lat": 51.1,
        "lon": 17.0,
    }
    place = map_overture_row(row)
    assert place.name == "Piekarnia Test"
    assert place.brand_name == "BrandX"
    assert place.country == "PL"
    assert place.address_freeform == "ul. Polska 1"
    assert place.websites == []
    assert place.socials == ["https://instagram.com/x"]
    assert place.source_refs[0].dataset == "meta"
    assert place.source_refs[0].license == "ODbL"


def test_map_overture_row_json_roundtrip_stable() -> None:
    place = map_overture_row(
        {
            "id": "x",
            "version": 1,
            "names": {"primary": None},
            "basic_category": "cafe",
            "taxonomy": {"primary": "cafe", "hierarchy": ["cafe"], "alternates": None},
            "confidence": None,
            "operating_status": None,
            "websites": [],
            "socials": [],
            "emails": [],
            "phones": [],
            "brand": None,
            "addresses": [],
            "sources": [],
            "lat": 51.1,
            "lon": 17.0,
        }
    )
    assert place.name is None
    assert json.loads(place.model_dump_json())["taxonomy_alternates"] == []
