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
    """Live Overture discovery must resolve a release id; schema may fall back.

    STAC may return null schema:version or be unavailable. The resolver then
    uses the official S3 release listing and/or taxonomy snapshot with a warning.
    """
    cfg = load_builtin_config()
    resolved = resolve_release(
        "latest",
        snapshot_schema_version=cfg.taxonomy_snapshot.schema_version,
    )
    assert resolved.release_id
    assert resolved.schema_version == cfg.taxonomy_snapshot.schema_version
    if resolved.schema_source == "taxonomy_snapshot_fallback":
        assert any(
            "stac_schema_version_missing" in warning or "stac_unavailable" in warning
            for warning in resolved.warnings
        )
    else:
        assert resolved.schema_source == "stac"
