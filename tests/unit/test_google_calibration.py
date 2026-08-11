"""Tests for Google match calibration prepare/evaluate."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from customer_finder.calibration import (
    evaluate_google_calibration,
    prepare_google_calibration,
)
from customer_finder.errors import ConfigError


def _leads_with_place_ids(path: Path, n: int = 10) -> None:
    fields = [
        "overture_id",
        "name",
        "lat",
        "lon",
        "distance_m",
        "category",
        "bucket",
        "score",
        "address",
        "locality",
        "google_place_id",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i in range(n):
            writer.writerow(
                {
                    "overture_id": f"id{i}",
                    "name": f"Cafe {i}",
                    "lat": "51.1",
                    "lon": "17.0",
                    "distance_m": str(i),
                    "category": "cafe",
                    "bucket": "social_only",
                    "score": str(80 - i),
                    "address": f"ul. {i}",
                    "locality": "Wrocław",
                    "google_place_id": f"ChIJ{i}",
                }
            )


def test_google_calibration_prepare_and_perfect_evaluate(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    review = tmp_path / "google-match-review.csv"
    summary = tmp_path / "google-match-review.summary.json"
    _leads_with_place_ids(leads, 10)
    prepare_google_calibration(leads, review, limit=10)
    with review.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["same_entity"] = "yes"
    with review.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    result = evaluate_google_calibration(review, summary)
    assert result["passed"] is True
    assert result["entity_match_precision"] == 1.0
    assert Path(result["approved_path"]).exists()


def test_google_calibration_uncertain_fails(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    review = tmp_path / "review.csv"
    summary = tmp_path / "review.summary.json"
    _leads_with_place_ids(leads, 10)
    prepare_google_calibration(leads, review, limit=10)
    with review.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for i, row in enumerate(rows):
        row["same_entity"] = "uncertain" if i == 0 else "yes"
    with review.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    result = evaluate_google_calibration(review, summary)
    assert result["passed"] is False


def test_google_calibration_too_few_ids(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    _leads_with_place_ids(leads, 3)
    with pytest.raises(ConfigError):
        prepare_google_calibration(leads, tmp_path / "out.csv", limit=10)
