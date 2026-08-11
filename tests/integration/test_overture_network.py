"""Optional network smoke tests (disabled by default via pytest addopts)."""

from __future__ import annotations

import os

import pytest

from customer_finder.overture import resolve_release
from customer_finder.settings import load_builtin_config

pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="Set RUN_NETWORK_TESTS=1 to enable live STAC checks",
)
def test_live_stac_resolves_latest_with_snapshot_fallback() -> None:
    """Live STAC must resolve a release id; schema:version may fall back.

    As of 2026-08-11 STAC child catalogs return null schema:version. The
    resolver then uses taxonomy_snapshot.schema_version and records a warning.
    """
    cfg = load_builtin_config()
    resolved = resolve_release(
        "latest",
        snapshot_schema_version=cfg.taxonomy_snapshot.schema_version,
    )
    assert resolved.release_id
    assert resolved.schema_version == cfg.taxonomy_snapshot.schema_version
    if resolved.schema_source == "taxonomy_snapshot_fallback":
        assert any("stac_schema_version_missing" in w for w in resolved.warnings)
    else:
        assert resolved.schema_source == "stac"
