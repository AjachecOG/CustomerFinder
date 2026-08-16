"""Manual calibration prepare / evaluate helpers."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from typing import Any

from customer_finder.errors import ArgumentError, ConfigError, OutputError
from customer_finder.models import CalibrationReview, Candidate, CandidateBucket, RawOverturePlace
from customer_finder.output import protect_formula
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


def approval_path_for_summary(summary_path: Path) -> Path:
    """Return the deterministic approval path associated with a summary."""
    if summary_path.name == "calibration.summary.json":
        return summary_path.with_name("calibration.approved.json")
    if summary_path.name.endswith(".summary.json"):
        return summary_path.with_name(summary_path.name.replace(".summary.json", ".approved.json"))
    return summary_path.with_name(summary_path.stem + ".approved.json")


def _resolve_approval_reference(approval_path: Path, raw_path: str) -> Path:
    reference = Path(raw_path)
    if reference.is_absolute():
        return reference
    candidates = (Path.cwd() / reference, approval_path.parent / reference.name)
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def inspect_calibration_approval(approval_path: Path) -> dict[str, Any]:
    """Validate an approval file and every hash it attests to without raising."""
    result: dict[str, Any] = {
        "path": str(approval_path),
        "exists": approval_path.is_file(),
        "valid": False,
        "calibration_csv": None,
        "summary_json": None,
        "error": None,
    }
    if not approval_path.is_file():
        return result
    try:
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("approval JSON must be an object")
        if payload.get("passed") is not True:
            raise ValueError("approval passed flag is not true")
        required = (
            "calibration_csv",
            "summary_json",
            "calibration_sha256",
            "summary_sha256",
        )
        if not all(isinstance(payload.get(key), str) and payload[key] for key in required):
            raise ValueError("approval is missing required string fields")

        calibration_csv = _resolve_approval_reference(
            approval_path, str(payload["calibration_csv"])
        )
        summary_json = _resolve_approval_reference(approval_path, str(payload["summary_json"]))
        result["calibration_csv"] = str(calibration_csv)
        result["summary_json"] = str(summary_json)
        if not calibration_csv.is_file():
            raise ValueError(f"approved calibration CSV not found: {calibration_csv}")
        if not summary_json.is_file():
            raise ValueError(f"approved summary JSON not found: {summary_json}")

        calibration_sha = _sha256(calibration_csv)
        summary_sha = _sha256(summary_json)
        if not hmac.compare_digest(calibration_sha, str(payload["calibration_sha256"])):
            raise ValueError("approved calibration CSV hash mismatch")
        if not hmac.compare_digest(summary_sha, str(payload["summary_sha256"])):
            raise ValueError("approved summary JSON hash mismatch")

        summary = json.loads(summary_json.read_text(encoding="utf-8"))
        if not isinstance(summary, dict) or summary.get("passed") is not True:
            raise ValueError("approved summary does not contain passed=true")
        if not hmac.compare_digest(str(summary.get("sha256") or ""), calibration_sha):
            raise ValueError("approved summary does not attest to the calibration CSV hash")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result["error"] = str(exc)
        return result

    result["valid"] = True
    return result


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
    prepared: list[dict[str, str]] = []
    for rank, row in enumerate(selected, start=1):
        candidate = _candidate_from_leads_row(row)
        prepared.append(
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
    save_calibration_rows(output_csv, prepared)
    return output_csv


def load_calibration_rows(path: Path) -> list[dict[str, str]]:
    """Load calibration CSV rows; missing file returns an empty list."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "") for key, value in row.items()} for row in csv.DictReader(handle)
        ]


def save_calibration_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Rewrite calibration CSV with idempotent spreadsheet-formula protection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(CALIBRATION_COLUMNS),
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {column: protect_formula(row.get(column, "")) for column in CALIBRATION_COLUMNS}
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise OutputError(f"Failed to write calibration CSV atomically: {path}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def update_calibration_review(
    path: Path,
    rank: int,
    *,
    entity_status: str,
    target_category: str,
    operating_status_review: str,
    independence: str,
    site_status: str,
    notes: str | None = None,
) -> dict[str, str]:
    """Validate and persist one complete five-field review."""
    rows = load_calibration_rows(path)
    if not rows:
        raise ArgumentError(f"Calibration CSV not found: {path}")
    match = next((row for row in rows if int(row["rank"]) == rank), None)
    if match is None:
        raise ArgumentError(f"Calibration rank {rank} not found in {path}")
    review = CalibrationReview(
        entity_status=entity_status,  # type: ignore[arg-type]
        target_category=target_category,  # type: ignore[arg-type]
        operating_status_review=operating_status_review,  # type: ignore[arg-type]
        independence=independence,  # type: ignore[arg-type]
        site_status=site_status,  # type: ignore[arg-type]
        notes=notes or None,
    )
    match["entity_status"] = review.entity_status or ""
    match["target_category"] = review.target_category or ""
    match["operating_status_review"] = review.operating_status_review or ""
    match["independence"] = review.independence or ""
    match["site_status"] = review.site_status or ""
    match["notes"] = review.notes or ""
    save_calibration_rows(path, rows)
    return match


def is_complete_review_row(row: dict[str, str]) -> bool:
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

    complete_rows = [row for row in rows if is_complete_review_row(row)]
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
        approved = approval_path_for_summary(summary_path)
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
