"""Unit tests for calibration prepare / evaluate."""

from __future__ import annotations

import csv
from pathlib import Path

from customer_finder.calibration import evaluate_calibration, prepare_calibration


def _write_leads(path: Path, n: int = 25) -> None:
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
                    "bucket": "likely_no_site",
                    "score": str(90 - i),
                    "address": f"ul. {i}",
                    "locality": "Wrocław",
                    "google_place_id": "",
                }
            )


def test_prepare_and_evaluate_pass(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    summary = tmp_path / "calibration.summary.json"
    _write_leads(leads, 25)
    prepare_calibration(leads, calib, limit=25)

    # Fill all 25 rows as passing reviews.
    with calib.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["entity_status"] = "valid"
        row["target_category"] = "yes"
        row["operating_status_review"] = "open"
        row["independence"] = "independent"
        row["site_status"] = "no_owned_site"
    with calib.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = evaluate_calibration(calib, summary)
    assert result["passed"] is True
    assert Path(result["approved_path"]).exists()
