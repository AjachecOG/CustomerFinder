"""Manual calibration prepare / evaluate helpers."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from customer_finder.errors import ArgumentError, ConfigError, OutputError
from customer_finder.models import CalibrationReview, Candidate, CandidateBucket, RawOverturePlace
from customer_finder.verify_links import maps_search_url

REVIEW_FIELDS = (
    "entity_status",
    "target_category",
    "operating_status_review",
    "independence",
    "site_status",
)

CALIBRATION_COLUMNS = (
    "rank",
    "overture_id",
    "name",
    "google_maps_url",
    *REVIEW_FIELDS,
    "notes",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_from_leads_row(row: dict[str, str]) -> Candidate:
    """Minimal Candidate used only to build Maps URLs from leads CSV."""
    place = RawOverturePlace(
        overture_id=row["overture_id"],
        version=0,
        name=row.get("name") or None,
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        address_freeform=row.get("address") or None,
        locality=row.get("locality") or None,
    )
    return Candidate(
        raw=place,
        distance_m=int(float(row.get("distance_m") or 0)),
        normalized_name=(row.get("name") or "").lower(),
        category_alias=row.get("category") or "cafe",
        bucket=CandidateBucket(row.get("bucket") or "unknown"),
        score=int(float(row.get("score") or 0)),
        score_reasons=[],
        google_place_id=row.get("google_place_id") or None,
    )


def prepare_calibration(
    leads_csv: Path,
    output_csv: Path,
    *,
    limit: int = 30,
    overwrite: bool = False,
) -> Path:
    if output_csv.exists() and not overwrite:
        raise OutputError(f"Calibration file already exists: {output_csv}")
    if not leads_csv.is_file():
        raise ArgumentError(f"Leads CSV not found: {leads_csv}")

    with leads_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = rows[:limit]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CALIBRATION_COLUMNS))
        writer.writeheader()
        for rank, row in enumerate(selected, start=1):
            candidate = _candidate_from_leads_row(row)
            writer.writerow(
                {
                    "rank": str(rank),
                    "overture_id": row["overture_id"],
                    "name": row.get("name") or "",
                    "google_maps_url": maps_search_url(candidate),
                    "entity_status": "",
                    "target_category": "",
                    "operating_status_review": "",
                    "independence": "",
                    "site_status": "",
                    "notes": "",
                }
            )
    return output_csv


def _is_complete(row: dict[str, str]) -> bool:
    values = [row.get(field, "").strip() for field in REVIEW_FIELDS]
    if all(not value for value in values):
        return False
    try:
        CalibrationReview(
            entity_status=values[0] or None,  # type: ignore[arg-type]
            target_category=values[1] or None,  # type: ignore[arg-type]
            operating_status_review=values[2] or None,  # type: ignore[arg-type]
            independence=values[3] or None,  # type: ignore[arg-type]
            site_status=values[4] or None,  # type: ignore[arg-type]
            notes=row.get("notes") or None,
        )
    except Exception as exc:
        raise ConfigError(f"Invalid calibration row rank={row.get('rank')}: {exc}") from exc
    return all(values)


def evaluate_calibration(
    calibration_csv: Path,
    summary_path: Path,
    *,
    expected_rows: int | None = None,
    top_n_metrics: int = 20,
) -> dict[str, Any]:
    if not calibration_csv.is_file():
        raise ArgumentError(f"Calibration CSV not found: {calibration_csv}")

    with calibration_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ConfigError("Calibration CSV is empty")

    ranks = [int(row["rank"]) for row in rows]
    if ranks != list(range(1, len(rows) + 1)):
        raise ConfigError("Calibration ranks must be contiguous starting at 1")

    ids = [row["overture_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ConfigError("Duplicate overture_id in calibration CSV")

    complete_rows = [row for row in rows if _is_complete(row)]
    reviewed = len(complete_rows)
    if reviewed < 20:
        raise ConfigError(f"Need at least 20 completely reviewed rows, got {reviewed}")

    def metrics_for(subset: list[dict[str, str]]) -> dict[str, float | int]:
        n = len(subset)
        target_independent = 0
        target_without_owned = 0
        chain = 0
        wrong = 0
        for row in subset:
            if row["independence"] == "chain":
                chain += 1
            if row["entity_status"] == "wrong_entity" or row["target_category"] == "no":
                wrong += 1
            independent = (
                row["entity_status"] == "valid"
                and row["target_category"] == "yes"
                and row["operating_status_review"] == "open"
                and row["independence"] == "independent"
            )
            if independent:
                target_independent += 1
                if row["site_status"] in {"no_owned_site", "social_only"}:
                    target_without_owned += 1
        return {
            "reviewed": n,
            "target_independent": target_independent,
            "target_precision": target_independent / n,
            "target_without_owned_site": target_without_owned,
            "no_site_precision": target_without_owned / n,
            "chain_ratio": chain / n,
            "wrong_ratio": wrong / n,
        }

    full_metrics = metrics_for(complete_rows)
    top20 = [row for row in complete_rows if int(row["rank"]) <= top_n_metrics]
    if len(top20) < min(top_n_metrics, reviewed):
        # Use first reviewed by rank order already present.
        top20 = complete_rows[:top_n_metrics]
    top20_metrics = metrics_for(top20)

    expected = expected_rows if expected_rows is not None else len(rows)
    passed = (
        reviewed == expected
        and float(top20_metrics["target_precision"]) >= 0.80
        and float(top20_metrics["no_site_precision"]) >= 0.70
    )

    summary: dict[str, Any] = {
        "file": str(calibration_csv),
        "sha256": _sha256(calibration_csv),
        "expected_rows": expected,
        "complete_rows": reviewed,
        "top20": top20_metrics,
        "all_reviewed": full_metrics,
        "thresholds": {
            "target_precision": 0.80,
            "no_site_precision": 0.70,
            "min_reviewed_for_report": 20,
            "require_all_prepared_complete_for_pass": True,
        },
        "passed": passed,
    }

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if passed:
        approved = summary_path.with_name(
            summary_path.name.replace(".summary.json", ".approved.json")
            if summary_path.name.endswith(".summary.json")
            else summary_path.stem + ".approved.json"
        )
        # Default name calibration.approved.json when summary is calibration.summary.json
        if summary_path.name == "calibration.summary.json":
            approved = summary_path.with_name("calibration.approved.json")
        approved.write_text(
            json.dumps(
                {
                    "calibration_csv": str(calibration_csv),
                    "summary_json": str(summary_path),
                    "calibration_sha256": summary["sha256"],
                    "summary_sha256": _sha256(summary_path),
                    "passed": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary["approved_path"] = str(approved)

    return summary


GOOGLE_CALIBRATION_COLUMNS = (
    "rank",
    "overture_id",
    "name",
    "google_maps_url",
    "google_place_id",
    "same_entity",
    "notes",
)


def prepare_google_calibration(
    leads_csv: Path,
    output_csv: Path,
    *,
    limit: int = 10,
    overwrite: bool = False,
) -> Path:
    if output_csv.exists() and not overwrite:
        raise OutputError(f"Google calibration file already exists: {output_csv}")
    if not leads_csv.is_file():
        raise ArgumentError(f"Leads CSV not found: {leads_csv}")

    with leads_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("google_place_id") or "").strip()]
    selected = rows[:limit]
    if len(selected) < limit:
        raise ConfigError(f"Need at least {limit} rows with google_place_id, found {len(selected)}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(GOOGLE_CALIBRATION_COLUMNS))
        writer.writeheader()
        for rank, row in enumerate(selected, start=1):
            candidate = _candidate_from_leads_row(row)
            writer.writerow(
                {
                    "rank": str(rank),
                    "overture_id": row["overture_id"],
                    "name": row.get("name") or "",
                    "google_maps_url": maps_search_url(candidate),
                    "google_place_id": row.get("google_place_id") or "",
                    "same_entity": "",
                    "notes": "",
                }
            )
    return output_csv


def evaluate_google_calibration(
    calibration_csv: Path,
    summary_path: Path,
    *,
    expected_rows: int = 10,
) -> dict[str, Any]:
    if not calibration_csv.is_file():
        raise ArgumentError(f"Google calibration CSV not found: {calibration_csv}")
    with calibration_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_rows:
        raise ConfigError(f"Expected {expected_rows} rows, got {len(rows)}")
    ids = [row["overture_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ConfigError("Duplicate overture_id in google calibration CSV")

    values = []
    for row in rows:
        value = (row.get("same_entity") or "").strip().lower()
        if value not in {"yes", "no", "uncertain"}:
            raise ConfigError(f"same_entity must be yes|no|uncertain (rank={row.get('rank')})")
        values.append(value)

    if any(v == "uncertain" for v in values):
        # uncertain does not satisfy the gate
        precision = 0.0
        passed = False
    else:
        yes = sum(1 for v in values if v == "yes")
        precision = yes / len(values)
        passed = precision == 1.0

    summary: dict[str, Any] = {
        "file": str(calibration_csv),
        "sha256": _sha256(calibration_csv),
        "reviewed": len(values),
        "entity_match_precision": precision,
        "passed": passed,
        "thresholds": {"entity_match_precision": 1.0, "required_rows": expected_rows},
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if passed:
        approved = summary_path.with_name("google-match-review.approved.json")
        if summary_path.name.endswith(".summary.json"):
            approved = summary_path.with_name(
                summary_path.name.replace(".summary.json", ".approved.json")
            )
        approved.write_text(
            json.dumps(
                {
                    "calibration_csv": str(calibration_csv),
                    "summary_json": str(summary_path),
                    "calibration_sha256": summary["sha256"],
                    "summary_sha256": _sha256(summary_path),
                    "passed": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary["approved_path"] = str(approved)
    return summary
