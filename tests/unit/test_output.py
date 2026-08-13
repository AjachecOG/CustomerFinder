"""Unit tests for CSV / atomic output helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from customer_finder.errors import OutputError
from customer_finder.models import Candidate, CandidateBucket, RawOverturePlace
from customer_finder.output import (
    CSV_COLUMNS,
    candidate_to_row,
    derive_output_paths,
    preflight_output,
    protect_formula,
    stale_output_warning,
    write_success_bundle,
)


def test_protect_formula_prefixes() -> None:
    for prefix in ("=", "+", "-", "@"):
        assert protect_formula(f"{prefix}cmd") == f"'{prefix}cmd"
    assert protect_formula("normal") == "normal"
    assert protect_formula('["a"]') == '["a"]'


def test_candidate_row_json_and_column_order() -> None:
    place = RawOverturePlace(
        overture_id="id1",
        version=1,
        name="=Evil",
        lat=51.1,
        lon=17.0,
        phones=["+48111"],
        source_refs=[],
    )
    candidate = Candidate(
        raw=place,
        distance_m=10,
        normalized_name="evil",
        category_alias="cafe",
        owned_domains=[],
        social_urls=[],
        aggregator_urls=[],
        other_urls=[],
        normalized_phones=["+48111"],
        is_chain=False,
        chain_reason=None,
        bucket=CandidateBucket.LIKELY_NO_SITE,
        score=50,
        score_reasons=["base:+10"],
        google_place_id=None,
    )
    row = candidate_to_row(candidate, overture_release="fixture")
    assert list(row.keys()) == list(CSV_COLUMNS)
    assert row["name"] == "'=Evil"
    assert json.loads(row["phones"]) == ["+48111"]
    assert json.loads(row["score_reasons"]) == ["base:+10"]


def test_preflight_refuses_existing_without_overwrite(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    paths = derive_output_paths(csv_path)
    csv_path.write_text("x", encoding="utf-8")
    with pytest.raises(OutputError):
        preflight_output(paths, overwrite=False)
    preflight_output(paths, overwrite=True)


def test_atomic_write_creates_complete_marker(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    paths = derive_output_paths(csv_path)
    preflight_output(paths, overwrite=False)
    place = RawOverturePlace(overture_id="a", version=1, name="A", lat=51.1, lon=17.0)
    candidate = Candidate(
        raw=place,
        distance_m=1,
        normalized_name="a",
        category_alias="cafe",
        bucket=CandidateBucket.LIKELY_NO_SITE,
        score=40,
        score_reasons=["base:+10"],
    )
    manifest = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "schema_version": "1",
    }
    write_success_bundle(
        paths,
        candidates=[candidate],
        overture_release="fixture",
        manifest=manifest,
        overwrite=False,
    )
    assert paths.csv_path.exists()
    assert paths.manifest_path.exists()
    assert paths.verify_links_path.exists()
    complete = json.loads(paths.complete_path.read_text(encoding="utf-8"))
    assert complete["run_id"] == manifest["run_id"]
    assert set(complete["sha256"]) == {
        "leads.csv",
        "leads.manifest.json",
        "leads.verify_links.txt",
    }


def test_atomic_write_rollback_when_complete_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_rollback_on_promote_failure(tmp_path, monkeypatch, ".complete")


@pytest.mark.parametrize("suffix", [".csv", ".manifest.json", ".verify_links.txt"])
def test_atomic_write_rollback_after_each_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    _assert_rollback_on_promote_failure(tmp_path, monkeypatch, suffix)


def _assert_rollback_on_promote_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    import os

    csv_path = tmp_path / "leads.csv"
    paths = derive_output_paths(csv_path)
    csv_path.write_text("old-csv", encoding="utf-8")
    paths.manifest_path.write_text("old-manifest", encoding="utf-8")
    paths.verify_links_path.write_text("old-links", encoding="utf-8")
    paths.complete_path.write_text("old-complete", encoding="utf-8")

    real_replace = os.replace

    def flaky_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if str(dst).endswith(suffix) and ".tmp-" in str(src):
            raise OSError("simulated promote failure")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    place = RawOverturePlace(overture_id="a", version=1, name="A", lat=51.1, lon=17.0)
    candidate = Candidate(
        raw=place,
        distance_m=1,
        normalized_name="a",
        category_alias="cafe",
        bucket=CandidateBucket.LIKELY_NO_SITE,
        score=40,
        score_reasons=["base:+10"],
    )
    with pytest.raises(OutputError, match="promote"):
        write_success_bundle(
            paths,
            candidates=[candidate],
            overture_release="fixture",
            manifest={"run_id": "22222222-2222-2222-2222-222222222222"},
            overwrite=True,
        )
    assert csv_path.read_text(encoding="utf-8") == "old-csv"
    assert paths.manifest_path.read_text(encoding="utf-8") == "old-manifest"
    assert paths.complete_path.read_text(encoding="utf-8") == "old-complete"


def test_stale_output_warning_when_fresh_until_passed(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    csv_path = tmp_path / "leads.csv"
    csv_path.write_text("x", encoding="utf-8")
    manifest = tmp_path / "leads.manifest.json"
    manifest.write_text(
        '{"data_fresh_until": "2020-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    warning = stale_output_warning(csv_path, now=datetime(2026, 8, 13, tzinfo=UTC))
    assert warning is not None
    assert "data_fresh_until" in warning
    assert "not deleted" in warning
    assert stale_output_warning(csv_path, now=datetime(2019, 1, 1, tzinfo=UTC)) is None
