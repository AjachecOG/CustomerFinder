"""Optional network smoke tests (disabled by default via pytest addopts)."""

from __future__ import annotations

import os

import pytest

from customer_finder.errors import OvertureError
from customer_finder.overture import resolve_release
from customer_finder.settings import load_builtin_config

pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="Set RUN_NETWORK_TESTS=1 to enable live STAC checks",
)
def test_live_stac_schema_version_present_or_documented() -> None:
    """Live STAC must expose schema:version for Milestone 2 gate.

    As of 2026-08-11, https://stac.overturemaps.org/2026-07-22.0/catalog.json
    returns ``schema:version: null`` / tag vNone. That violates plan §9.1 and
    correctly raises OvertureError until Overture publishes the field again.
    """
    cfg = load_builtin_config()
    try:
        resolved = resolve_release(
            "latest",
            snapshot_schema_version=cfg.taxonomy_snapshot.schema_version,
        )
    except OvertureError as exc:
        assert "schema:version" in exc.message
        pytest.xfail(
            "Live STAC currently returns null schema:version; "
            "offline Milestone 2 is complete. Owner decision needed for fallback."
        )
    assert resolved.schema_version == cfg.taxonomy_snapshot.schema_version
