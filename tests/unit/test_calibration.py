"""Unit tests for calibration prepare / evaluate."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from customer_finder.calibration import (
    evaluate_calibration,
    inspect_calibration_approval,
    prepare_calibration,
    update_calibration_review,
)
from customer_finder.errors import OutputError


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
                }
            )


def test_prepare_protects_formula_like_names(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    _write_leads(leads, 1)
    with leads.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["name"] = "=cmd|'/c calc'!A0"
    with leads.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    prepare_calibration(leads, calib, limit=1)
    with calib.open(encoding="utf-8-sig", newline="") as handle:
        out = list(csv.DictReader(handle))
    assert out[0]["name"].startswith("'=")


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
    approval = Path(result["approved_path"])
    assert approval.exists()
    inspected = inspect_calibration_approval(approval)
    assert inspected["valid"] is True
    assert inspected["error"] is None

    calib.write_text(calib.read_text(encoding="utf-8-sig") + "\n", encoding="utf-8-sig")
    tampered = inspect_calibration_approval(approval)
    assert tampered["valid"] is False
    assert "hash mismatch" in str(tampered["error"])


def test_inspect_calibration_approval_handles_missing_and_invalid_json(tmp_path: Path) -> None:
    missing = inspect_calibration_approval(tmp_path / "missing.approved.json")
    assert missing == {
        "path": str(tmp_path / "missing.approved.json"),
        "exists": False,
        "valid": False,
        "calibration_csv": None,
        "summary_json": None,
        "error": None,
    }

    invalid_path = tmp_path / "invalid.approved.json"
    invalid_path.write_text("[]", encoding="utf-8")
    invalid = inspect_calibration_approval(invalid_path)
    assert invalid["exists"] is True
    assert invalid["valid"] is False
    assert "must be an object" in str(invalid["error"])

    invalid_path.write_bytes(b"\xff\xfe")
    non_utf8 = inspect_calibration_approval(invalid_path)
    assert non_utf8["valid"] is False
    assert non_utf8["error"]


def test_update_calibration_review_persists_one_row(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    _write_leads(leads, 3)
    prepare_calibration(leads, calib, limit=3)
    updated = update_calibration_review(
        calib,
        2,
        entity_status="valid",
        target_category="yes",
        operating_status_review="open",
        independence="independent",
        site_status="social_only",
        notes="tylko Instagram",
    )
    assert updated["rank"] == "2"
    assert updated["site_status"] == "social_only"
    with calib.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["notes"] == "tylko Instagram"
    assert rows[0]["entity_status"] == ""


def test_update_calibration_review_protects_formula_like_notes(tmp_path: Path) -> None:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    _write_leads(leads, 1)
    prepare_calibration(leads, calib, limit=1)

    update_calibration_review(
        calib,
        1,
        entity_status="valid",
        target_category="yes",
        operating_status_review="open",
        independence="independent",
        site_status="no_owned_site",
        notes='=HYPERLINK("https://example.test")',
    )
    with calib.open(encoding="utf-8-sig", newline="") as handle:
        first_save = next(iter(csv.DictReader(handle)))
    assert first_save["notes"].startswith("'=")

    update_calibration_review(
        calib,
        1,
        entity_status="valid",
        target_category="yes",
        operating_status_review="open",
        independence="independent",
        site_status="no_owned_site",
        notes=first_save["notes"],
    )
    with calib.open(encoding="utf-8-sig", newline="") as handle:
        second_save = next(iter(csv.DictReader(handle)))
    assert second_save["notes"] == first_save["notes"]


def test_atomic_review_save_preserves_existing_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    _write_leads(leads, 1)
    prepare_calibration(leads, calib, limit=1)
    original = calib.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("customer_finder.calibration.os.replace", fail_replace)
    with pytest.raises(OutputError, match="atomically"):
        update_calibration_review(
            calib,
            1,
            entity_status="valid",
            target_category="yes",
            operating_status_review="open",
            independence="independent",
            site_status="no_owned_site",
        )

    assert calib.read_bytes() == original
    assert list(tmp_path.glob(".calibration.csv.tmp-*")) == []


def test_evaluate_fixture_reviewed_file() -> None:
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "calibration_reviewed.csv"
    summary = Path("/tmp/calibration_fixture.summary.json")
    result = evaluate_calibration(fixture, summary, expected_rows=25)
    assert result["complete_rows"] == 25
    assert float(result["top20"]["target_precision"]) >= 0.80
    assert float(result["top20"]["no_site_precision"]) >= 0.70
    # Row 21-22 are chain/wrong so full-file pass thresholds may still pass top20.
    assert "sha256" in result
