"""Overture Maps Places access via STAC + DuckDB GeoParquet."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import duckdb
import httpx

from customer_finder import __version__
from customer_finder.errors import ConfigError, OvertureError
from customer_finder.geometry import BBox, compute_bbox, within_radius_m
from customer_finder.models import RawOverturePlace, SourceRef
from customer_finder.settings import AppConfig

STAC_CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
S3_RELEASE_LIST_URL = (
    "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/"
    "?list-type=2&delimiter=%2F&prefix=release%2F"
)
OVERTURE_ALLOWED_HOSTS = frozenset(
    {
        "stac.overturemaps.org",
        "overturemaps-us-west-2.s3.us-west-2.amazonaws.com",
    }
)
RELEASE_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
SCHEMA_VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")

USER_AGENT = f"customer-finder/{__version__}"
HTTP_TIMEOUT_S = 30.0

# Evidence (2026-08-11): STAC child catalogs publish schema:version=null /
# schema:tag=.../vNone for 2026-07-22.0 and 2026-06-17.0. GitHub schema tag
# v1.18.0 was published 2026-07-21 (day before the July Places release).
# Minimal contract amendment to plan §9.1: fall back to taxonomy_snapshot
# schema_version with an explicit warning when STAC omits the field.
STAC_SCHEMA_FALLBACK_WARNING = (
    "stac_schema_version_missing: STAC child catalog schema:version is null; "
    "using taxonomy_snapshot.schema_version as temporary fallback "
    "(checked 2026-08-11 against https://stac.overturemaps.org/)"
)
STAC_RELEASE_FALLBACK_WARNING = (
    "stac_unavailable: discovered latest release from the official public S3 listing; "
    "using taxonomy_snapshot.schema_version"
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "id",
    "version",
    "names",
    "basic_category",
    "taxonomy",
    "confidence",
    "operating_status",
    "websites",
    "socials",
    "emails",
    "phones",
    "brand",
    "addresses",
    "sources",
    "bbox",
    "geometry",
)


@dataclass(frozen=True, slots=True)
class ResolvedRelease:
    release_id: str
    schema_version: str
    parquet_glob: str
    catalog_url: str
    schema_source: Literal["stac", "taxonomy_snapshot_fallback"] = "stac"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryStats:
    raw_category_bbox: int
    after_radius: int
    bbox_total_diagnostic: int | None = None


def _normalize_schema_version(raw: str) -> str:
    match = SCHEMA_VERSION_RE.match(raw.strip())
    if not match:
        raise OvertureError(f"Unrecognized schema:version {raw!r}; expected X.Y.Z or vX.Y.Z")
    return match.group(1)


def _assert_overture_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OVERTURE_ALLOWED_HOSTS:
        raise OvertureError(f"Refusing Overture catalog URL host={host!r}")


def _overture_request_hook(request: httpx.Request) -> None:
    _assert_overture_url(str(request.url))


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_S,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
        event_hooks={"request": [_overture_request_hook]},
    )


def _get_json_with_backoff(client: httpx.Client, url: str) -> dict[str, Any]:
    """Fetch JSON with up to 3 attempts (waits 1s, then 2s) per plan §9.1."""
    import time

    delays = (0.0, 1.0, 2.0)
    last_exc: Exception | None = None
    _assert_overture_url(url)
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise OvertureError(f"STAC response is not an object: {url}")
            return data
        except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt == len(delays):
                break
    assert last_exc is not None
    raise OvertureError(
        f"STAC unavailable at stage=fetch url={url}. "
        f"Retry exhausted ({last_exc!s}). Use --overture-release YYYY-MM-DD.N"
    ) from last_exc


def _get_text_with_backoff(client: httpx.Client, url: str) -> str:
    """Fetch an official Overture text resource with bounded retries."""
    import time

    delays = (0.0, 1.0, 2.0)
    last_exc: Exception | None = None
    _assert_overture_url(url)
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.text
        except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt == len(delays):
                break
    assert last_exc is not None
    raise OvertureError(
        f"Overture release listing unavailable at stage=fetch url={url}. "
        f"Retry exhausted ({last_exc!s}). Use --overture-release YYYY-MM-DD.N"
    ) from last_exc


def _latest_release_from_s3(client: httpx.Client) -> str:
    """Discover the newest retained release from Overture's public S3 bucket."""
    payload = _get_text_with_backoff(client, S3_RELEASE_LIST_URL)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise OvertureError(
            f"Overture S3 release listing is invalid XML (url={S3_RELEASE_LIST_URL})"
        ) from exc

    releases: list[str] = []
    for element in root.iter():
        if not element.tag.endswith("Prefix") or not element.text:
            continue
        match = re.fullmatch(r"release/(\d{4}-\d{2}-\d{2}\.\d+)/", element.text)
        if match and RELEASE_ID_RE.match(match.group(1)):
            releases.append(match.group(1))
    if not releases:
        raise OvertureError(
            f"Overture S3 release listing contains no valid releases (url={S3_RELEASE_LIST_URL})"
        )

    def release_key(release_id: str) -> tuple[datetime, int]:
        date_part, revision = release_id.rsplit(".", 1)
        return datetime.strptime(date_part, "%Y-%m-%d"), int(revision)

    return max(releases, key=release_key)


def _child_href(catalog: dict[str, Any], release_id: str, *, catalog_url: str) -> str:
    for link in catalog.get("links", []):
        if not isinstance(link, dict) or link.get("rel") != "child":
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        absolute = urljoin(catalog_url, href)
        title = str(link.get("title", ""))
        if release_id in href or release_id in absolute or release_id in title:
            return absolute
    raise OvertureError(
        f"STAC catalog has no child link for release {release_id!r} "
        f"(url={catalog_url}). Use --overture-release with a listed release."
    )


def _extract_schema_version(
    child_catalog: dict[str, Any],
    *,
    url: str,
    snapshot_schema_version: str | None,
) -> tuple[str, Literal["stac", "taxonomy_snapshot_fallback"], tuple[str, ...]]:
    raw = child_catalog.get("schema:version")
    if raw is None or raw == "":
        if snapshot_schema_version:
            return (
                _normalize_schema_version(snapshot_schema_version),
                "taxonomy_snapshot_fallback",
                (STAC_SCHEMA_FALLBACK_WARNING + f" url={url}",),
            )
        raise OvertureError(
            f"STAC child catalog missing schema:version (url={url}). "
            "Cannot compare against taxonomy_snapshot; update STAC handling "
            "or pin a release once Overture publishes schema:version again."
        )
    if not isinstance(raw, str):
        raise OvertureError(
            f"STAC schema:version must be a string, got {type(raw).__name__} (url={url})"
        )
    return _normalize_schema_version(raw), "stac", ()


def _parquet_glob(release_id: str) -> str:
    return f"s3://overturemaps-us-west-2/release/{release_id}/theme=places/type=place/*"


def resolve_release(
    release: str,
    *,
    client: httpx.Client | None = None,
    snapshot_schema_version: str | None = None,
) -> ResolvedRelease:
    """Resolve latest/explicit release id, schema version, and Places parquet glob.

    When STAC is unavailable and the user passed an explicit release id, the
    release is accepted without STAC and ``snapshot_schema_version`` is used so
    the pipeline can continue (plan §9.1). If STAC is unavailable, ``latest``
    is discovered from Overture's official public S3 listing and uses the
    taxonomy snapshot schema version with an explicit warning.
    """
    owns_client = client is None
    http = client or _http_client()
    try:
        if release != "latest" and not RELEASE_ID_RE.match(release):
            raise OvertureError(f"Invalid overture release id {release!r}; expected YYYY-MM-DD.N")

        try:
            catalog = _get_json_with_backoff(http, STAC_CATALOG_URL)
        except OvertureError as stac_exc:
            if release == "latest":
                if not snapshot_schema_version:
                    raise stac_exc
                release_id = _latest_release_from_s3(http)
                return ResolvedRelease(
                    release_id=release_id,
                    schema_version=_normalize_schema_version(snapshot_schema_version),
                    parquet_glob=_parquet_glob(release_id),
                    catalog_url=S3_RELEASE_LIST_URL,
                    schema_source="taxonomy_snapshot_fallback",
                    warnings=(
                        f"{STAC_RELEASE_FALLBACK_WARNING}={snapshot_schema_version} "
                        f"release={release_id}",
                    ),
                )
            if not snapshot_schema_version:
                raise OvertureError(
                    f"STAC unavailable at stage=resolve url={STAC_CATALOG_URL}. "
                    "Pass an explicit --overture-release and ensure taxonomy "
                    "snapshot schema_version is available."
                ) from stac_exc
            return ResolvedRelease(
                release_id=release,
                schema_version=_normalize_schema_version(snapshot_schema_version),
                parquet_glob=_parquet_glob(release),
                catalog_url=STAC_CATALOG_URL,
                schema_source="taxonomy_snapshot_fallback",
                warnings=(
                    "stac_unavailable: using explicit release with taxonomy_snapshot "
                    f"schema_version={snapshot_schema_version}",
                ),
            )

        if release == "latest":
            latest = catalog.get("latest")
            if not isinstance(latest, str) or not RELEASE_ID_RE.match(latest):
                raise OvertureError(
                    f"STAC catalog latest field invalid: {latest!r} (url={STAC_CATALOG_URL})"
                )
            release_id = latest
        else:
            release_id = release

        child_url = _child_href(catalog, release_id, catalog_url=STAC_CATALOG_URL)
        child = _get_json_with_backoff(http, child_url)
        schema_version, schema_source, warnings = _extract_schema_version(
            child, url=child_url, snapshot_schema_version=snapshot_schema_version
        )
        return ResolvedRelease(
            release_id=release_id,
            schema_version=schema_version,
            parquet_glob=_parquet_glob(release_id),
            catalog_url=child_url,
            schema_source=schema_source,
            warnings=warnings,
        )
    finally:
        if owns_client:
            http.close()


def assert_schema_matches_snapshot(resolved: ResolvedRelease, config: AppConfig) -> None:
    expected = config.taxonomy_snapshot.schema_version
    if resolved.schema_version != expected:
        raise OvertureError(
            f"Overture schema:version {resolved.schema_version} differs from "
            f"taxonomy snapshot {expected}. Update taxonomy_snapshot.yml and "
            f"categories.yml after human review (release={resolved.release_id})."
        )


def connect_duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    _ensure_extensions(con)
    return con


def _ensure_extensions(con: duckdb.DuckDBPyConnection) -> None:
    for ext in ("httpfs", "spatial"):
        try:
            con.execute(f"LOAD {ext}")
        except duckdb.Error:
            con.execute(f"INSTALL {ext}")
            con.execute(f"LOAD {ext}")
    con.execute("SET s3_region='us-west-2'")
    con.execute("SET enable_geoparquet_conversion=true")


def check_schema(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    *,
    release_id: str,
) -> None:
    """Fail loudly if required columns are missing (never treat as zero rows)."""
    try:
        rows = con.execute(
            "SELECT name FROM parquet_schema(?)",
            [parquet_path],
        ).fetchall()
    except duckdb.Error as exc:
        raise OvertureError(
            f"Failed to read parquet schema for release={release_id}: {exc}"
        ) from exc
    present = {str(r[0]) for r in rows}
    # Nested parquet fields may appear as top-level or with parent prefix.
    top_level = {name.split(".")[0] for name in present}
    missing = [col for col in REQUIRED_COLUMNS if col not in top_level]
    if missing:
        raise OvertureError(
            f"Overture Places schema missing columns {missing} for release={release_id}"
        )


def _in_clause(count: int) -> str:
    if count <= 0:
        raise ConfigError("Cannot build SQL IN clause with zero values")
    return "(" + ",".join(["?"] * count) + ")"


def _list_value_clause(count: int) -> str:
    if count <= 0:
        raise ConfigError("Cannot build list_value with zero values")
    return "list_value(" + ",".join(["?"] * count) + ")"


def build_category_sql(basic_codes: list[str], taxonomy_codes: list[str]) -> tuple[str, list[str]]:
    """Build parameterized category predicate; never interpolate raw codes."""
    clauses: list[str] = []
    params: list[str] = []
    if basic_codes:
        clauses.append(f"basic_category IN {_in_clause(len(basic_codes))}")
        params.extend(basic_codes)
    if taxonomy_codes:
        clauses.append(f"taxonomy.primary IN {_in_clause(len(taxonomy_codes))}")
        params.extend(taxonomy_codes)
        lv = _list_value_clause(len(taxonomy_codes))
        clauses.append(f"list_has_any(coalesce(taxonomy.hierarchy, []), {lv})")
        params.extend(taxonomy_codes)
        clauses.append(f"list_has_any(coalesce(taxonomy.alternates, []), {lv})")
        params.extend(taxonomy_codes)
    if not clauses:
        raise ConfigError("No Overture category codes configured for selected aliases")
    return "(" + " OR ".join(clauses) + ")", params


def category_codes_for_aliases(
    aliases: list[str], config: AppConfig
) -> tuple[list[str], list[str]]:
    basic: list[str] = []
    taxonomy: list[str] = []
    seen_b: set[str] = set()
    seen_t: set[str] = set()
    for alias in aliases:
        mapping = config.mapping_for(alias)
        for code in mapping.overture_basic:
            if code not in seen_b:
                seen_b.add(code)
                basic.append(code)
        for code in mapping.overture_taxonomy:
            if code not in seen_t:
                seen_t.add(code)
                taxonomy.append(code)
    return basic, taxonomy


def query_category_bbox(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    bbox: BBox,
    *,
    basic_codes: list[str],
    taxonomy_codes: list[str],
    release_id: str,
) -> tuple[list[dict[str, Any]], QueryStats]:
    """Run bbox+category SQL and return raw row dicts plus counters."""
    check_schema(con, parquet_path, release_id=release_id)
    category_sql, category_params = build_category_sql(basic_codes, taxonomy_codes)
    sql = f"""
        SELECT
            id,
            version,
            names,
            basic_category,
            taxonomy,
            confidence,
            operating_status,
            websites,
            socials,
            emails,
            phones,
            brand,
            addresses,
            sources,
            bbox,
            ST_X(geometry) AS lon,
            ST_Y(geometry) AS lat
        FROM read_parquet(?, hive_partitioning = true)
        WHERE bbox.xmin BETWEEN ? AND ?
          AND bbox.ymin BETWEEN ? AND ?
          AND {category_sql}
        ORDER BY id
    """
    params: list[Any] = [
        parquet_path,
        bbox.xmin,
        bbox.xmax,
        bbox.ymin,
        bbox.ymax,
        *category_params,
    ]
    try:
        result = con.execute(sql, params)
        columns = [col[0] for col in result.description]
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    except duckdb.Error as exc:
        raise OvertureError(f"DuckDB Places query failed for release={release_id}: {exc}") from exc

    bbox_total: int | None = None
    if not rows:
        try:
            count_row = con.execute(
                """
                SELECT COUNT(*) FROM read_parquet(?, hive_partitioning = true)
                WHERE bbox.xmin BETWEEN ? AND ?
                  AND bbox.ymin BETWEEN ? AND ?
                """,
                [parquet_path, bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax],
            ).fetchone()
            if count_row is None:
                raise OvertureError(
                    f"DuckDB diagnostic COUNT returned no row for release={release_id}"
                )
            bbox_total = int(count_row[0])
        except duckdb.Error as exc:
            raise OvertureError(
                f"DuckDB diagnostic COUNT failed for release={release_id}: {exc}"
            ) from exc

    stats = QueryStats(
        raw_category_bbox=len(rows),
        after_radius=0,
        bbox_total_diagnostic=bbox_total,
    )
    return rows, stats


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    # DuckDB may return array-like tuples
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _struct_get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    # duckdb might return named tuples / objects with __getitem__
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, None)


def _parse_update_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def map_overture_row(row: dict[str, Any]) -> RawOverturePlace:
    """Map a DuckDB result row to RawOverturePlace (explicit field mapping)."""
    names = row.get("names")
    name = _struct_get(names, "primary")
    if name is not None:
        name = str(name)

    taxonomy = row.get("taxonomy") or {}
    taxonomy_primary = _struct_get(taxonomy, "primary")
    hierarchy = [str(x) for x in _as_list(_struct_get(taxonomy, "hierarchy"))]
    alternates = [str(x) for x in _as_list(_struct_get(taxonomy, "alternates"))]

    brand = row.get("brand")
    brand_name = None
    if brand is not None:
        brand_names = _struct_get(brand, "names")
        primary_brand = _struct_get(brand_names, "primary")
        if primary_brand is not None:
            brand_name = str(primary_brand)

    addresses = _as_list(row.get("addresses"))
    chosen = None
    for addr in addresses:
        country_raw = _struct_get(addr, "country")
        if str(country_raw or "").upper() == "PL":
            chosen = addr
            break
    if chosen is None and addresses:
        chosen = addresses[0]

    address_freeform = None
    locality = None
    postcode = None
    country = None
    if chosen is not None:
        freeform = _struct_get(chosen, "freeform")
        address_freeform = str(freeform) if freeform is not None else None
        loc = _struct_get(chosen, "locality")
        locality = str(loc) if loc is not None else None
        pc = _struct_get(chosen, "postcode")
        postcode = str(pc) if pc is not None else None
        cc = _struct_get(chosen, "country")
        country = str(cc).upper() if cc is not None else None

    source_refs: list[SourceRef] = []
    for src in _as_list(row.get("sources")):
        dataset = _struct_get(src, "dataset")
        if dataset is None:
            continue
        source_refs.append(
            SourceRef(
                dataset=str(dataset),
                license=(
                    str(_struct_get(src, "license"))
                    if _struct_get(src, "license") is not None
                    else None
                ),
                property_path=(
                    str(_struct_get(src, "property"))
                    if _struct_get(src, "property") is not None
                    else (
                        str(_struct_get(src, "property_path"))
                        if _struct_get(src, "property_path") is not None
                        else None
                    )
                ),
                update_time=_parse_update_time(_struct_get(src, "update_time")),
            )
        )

    lat = row.get("lat")
    lon = row.get("lon")
    if lat is None or lon is None:
        raise OvertureError(f"Row {row.get('id')!r} missing ST_X/ST_Y coordinates")
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError) as exc:
        raise OvertureError(f"Row {row.get('id')!r} has non-numeric coordinates") from exc
    if not math.isfinite(lat_f) or not math.isfinite(lon_f):
        raise OvertureError(f"Row {row.get('id')!r} has non-finite coordinates")
    if not -90.0 <= lat_f <= 90.0 or not -180.0 <= lon_f <= 180.0:
        raise OvertureError(
            f"Row {row.get('id')!r} has out-of-range coordinates lat={lat_f} lon={lon_f}"
        )

    return RawOverturePlace(
        overture_id=str(row["id"]),
        version=int(row["version"]),
        name=name,
        lat=lat_f,
        lon=lon_f,
        basic_category=(
            str(row["basic_category"]) if row.get("basic_category") is not None else None
        ),
        taxonomy_primary=str(taxonomy_primary) if taxonomy_primary is not None else None,
        taxonomy_hierarchy=hierarchy,
        taxonomy_alternates=alternates,
        confidence=(float(row["confidence"]) if row.get("confidence") is not None else None),
        operating_status=(
            str(row["operating_status"]) if row.get("operating_status") is not None else None
        ),
        websites=[str(x) for x in _as_list(row.get("websites"))],
        socials=[str(x) for x in _as_list(row.get("socials"))],
        emails=[str(x) for x in _as_list(row.get("emails"))],
        phones=[str(x) for x in _as_list(row.get("phones"))],
        brand_name=brand_name,
        address_freeform=address_freeform,
        locality=locality,
        postcode=postcode,
        country=country,
        source_refs=source_refs,
    )


def filter_by_radius(
    places: list[RawOverturePlace],
    *,
    center_lat: float,
    center_lon: float,
    radius_km: float,
) -> list[tuple[RawOverturePlace, int]]:
    """Exact circular filter; distance_m is rounded haversine metres."""
    kept: list[tuple[RawOverturePlace, int]] = []
    for place in places:
        inside, distance_m = within_radius_m(
            center_lat, center_lon, place.lat, place.lon, radius_km
        )
        if inside:
            kept.append((place, distance_m))
    return kept


def fetch_places(
    *,
    parquet_path: str,
    center_lat: float,
    center_lon: float,
    radius_km: float,
    aliases: list[str],
    config: AppConfig,
    release_id: str,
    con: duckdb.DuckDBPyConnection | None = None,
) -> tuple[list[tuple[RawOverturePlace, int]], QueryStats]:
    """End-to-end offline/online Places fetch for a search center."""
    owns = con is None
    connection = con or connect_duckdb()
    try:
        bbox = compute_bbox(center_lat, center_lon, radius_km)
        basic, taxonomy = category_codes_for_aliases(aliases, config)
        rows, stats = query_category_bbox(
            connection,
            parquet_path,
            bbox,
            basic_codes=basic,
            taxonomy_codes=taxonomy,
            release_id=release_id,
        )
        places = [map_overture_row(row) for row in rows]
        filtered = filter_by_radius(
            places,
            center_lat=center_lat,
            center_lon=center_lon,
            radius_km=radius_km,
        )
        stats = QueryStats(
            raw_category_bbox=stats.raw_category_bbox,
            after_radius=len(filtered),
            bbox_total_diagnostic=stats.bbox_total_diagnostic,
        )
        return filtered, stats
    finally:
        if owns:
            connection.close()


def local_fixture_path() -> Path:
    """Path to the offline integration parquet fixture."""
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "overture_places.parquet"
