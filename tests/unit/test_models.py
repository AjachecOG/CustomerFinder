"""Unit tests for Pydantic models (Milestone 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from customer_finder.models import (
    CalibrationReview,
    Candidate,
    CandidateBucket,
    RawOverturePlace,
    SearchRequest,
    SourceRef,
)


def test_search_request_accepts_poland_point(tmp_path: Path) -> None:
    out = tmp_path / "leads.csv"
    req = SearchRequest(
        lat=51.1079,
        lon=17.0385,
        radius_km=3,
        categories="cafe, bakery, cafe",
        output_path=out,
    )
    assert req.categories == ["cafe", "bakery"]
    assert req.output_path == out
    assert req.min_score == 0


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("lat", {"lat": 40.0, "lon": 17.0, "radius_km": 1, "categories": ["cafe"]}),
        ("lon", {"lat": 51.0, "lon": 0.0, "radius_km": 1, "categories": ["cafe"]}),
        ("radius_km", {"lat": 51.0, "lon": 17.0, "radius_km": 0, "categories": ["cafe"]}),
        ("radius_km", {"lat": 51.0, "lon": 17.0, "radius_km": 11, "categories": ["cafe"]}),
    ],
)
def test_search_request_rejects_out_of_range(
    field: str, kwargs: dict[str, object], tmp_path: Path
) -> None:
    with pytest.raises(ValidationError) as exc:
        SearchRequest(output_path=tmp_path / "out.csv", **kwargs)  # type: ignore[arg-type]
    assert field in str(exc.value)


def test_search_request_rejects_unknown_empty_and_sqlish_categories(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            lat=51.1,
            lon=17.0,
            radius_km=1,
            categories="cafe,,bakery",
            output_path=tmp_path / "out.csv",
        )


def test_search_request_output_must_be_csv(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            lat=51.1,
            lon=17.0,
            radius_km=1,
            categories=["cafe"],
            output_path=tmp_path / "out.txt",
        )


def test_search_request_rejects_removed_google_fields(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            lat=51.1079,
            lon=17.0385,
            radius_km=3,
            categories=["cafe"],
            output_path=tmp_path / "out.csv",
            enrich="google",  # type: ignore[call-arg]
        )


def test_raw_place_none_lists_become_empty() -> None:
    place = RawOverturePlace(
        overture_id="abc",
        version=1,
        lat=51.1,
        lon=17.0,
        websites=None,  # type: ignore[arg-type]
        socials=None,  # type: ignore[arg-type]
        source_refs=None,  # type: ignore[arg-type]
    )
    assert place.websites == []
    assert place.socials == []
    assert place.source_refs == []


def test_calibration_review_partial_row_rejected() -> None:
    with pytest.raises(ValidationError):
        CalibrationReview(entity_status="valid")


def test_calibration_review_complete_or_empty_ok() -> None:
    empty = CalibrationReview()
    assert empty.entity_status is None
    full = CalibrationReview(
        entity_status="valid",
        target_category="yes",
        operating_status_review="open",
        independence="independent",
        site_status="no_owned_site",
    )
    assert full.site_status == "no_owned_site"


def test_candidate_score_bounds() -> None:
    raw = RawOverturePlace(overture_id="x", version=0, lat=51.1, lon=17.0)
    with pytest.raises(ValidationError):
        Candidate(
            raw=raw,
            distance_m=10,
            normalized_name="x",
            category_alias="cafe",
            bucket=CandidateBucket.LIKELY_NO_SITE,
            score=101,
        )


def test_source_ref_keeps_license_with_dataset() -> None:
    ref = SourceRef(dataset="meta", license="ODbL", property_path="/properties/names")
    assert ref.dataset == "meta"
    assert ref.license == "ODbL"
