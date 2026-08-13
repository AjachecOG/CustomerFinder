"""Atomic CSV / manifest / verify-links / complete-marker writers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from customer_finder import __version__
from customer_finder.errors import OutputError
from customer_finder.models import Candidate
from customer_finder.verify_links import DEFAULT_VERIFY_LINK_LIMIT, format_verify_links

CSV_COLUMNS: tuple[str, ...] = (
    "overture_id",
    "overture_release",
    "name",
    "category",
    "bucket",
    "score",
    "score_reasons",
    "address",
    "locality",
    "postcode",
    "country",
    "lat",
    "lon",
    "distance_m",
    "phones",
    "emails",
    "socials",
    "aggregators",
    "owned_domains",
    "brand_name",
    "is_chain",
    "chain_reason",
    "confidence",
    "operating_status",
    "google_place_id",
    "source_refs",
)


@dataclass(frozen=True, slots=True)
class OutputPaths:
    csv_path: Path
    manifest_path: Path
    verify_links_path: Path
    complete_path: Path

    @property
    def stem(self) -> str:
        return self.csv_path.stem

    def all_final(self) -> tuple[Path, ...]:
        return (
            self.csv_path,
            self.manifest_path,
            self.verify_links_path,
            self.complete_path,
        )


def derive_output_paths(csv_path: Path) -> OutputPaths:
    return OutputPaths(
        csv_path=csv_path,
        manifest_path=csv_path.with_name(f"{csv_path.stem}.manifest.json"),
        verify_links_path=csv_path.with_name(f"{csv_path.stem}.verify_links.txt"),
        complete_path=csv_path.with_name(f"{csv_path.stem}.complete"),
    )


def failed_manifest_path(csv_path: Path) -> Path:
    return csv_path.with_name(f"{csv_path.stem}.failed.manifest.json")


def stale_output_warning(csv_path: Path, *, now: datetime | None = None) -> str | None:
    """Warn when reading a result past data_fresh_until; never delete files (plan §15.3)."""
    manifest_path = derive_output_paths(csv_path).manifest_path
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get("data_fresh_until")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        fresh_until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if fresh_until.tzinfo is None:
        fresh_until = fresh_until.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    if moment <= fresh_until:
        return None
    return (
        f"data_fresh_until {raw} has passed for {csv_path}; "
        "re-run search on a current Overture release (files were not deleted)"
    )


def protect_formula(value: str) -> str:
    stripped = value.lstrip()
    if stripped[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def candidate_to_row(candidate: Candidate, *, overture_release: str) -> dict[str, str]:
    raw = candidate.raw
    row = {
        "overture_id": raw.overture_id,
        "overture_release": overture_release,
        "name": raw.name or "",
        "category": candidate.category_alias,
        "bucket": candidate.bucket.value,
        "score": str(candidate.score),
        "score_reasons": _json_cell(candidate.score_reasons),
        "address": raw.address_freeform or "",
        "locality": raw.locality or "",
        "postcode": raw.postcode or "",
        "country": raw.country or "",
        "lat": str(raw.lat),
        "lon": str(raw.lon),
        "distance_m": str(candidate.distance_m),
        "phones": _json_cell(raw.phones),
        "emails": _json_cell(raw.emails),
        "socials": _json_cell(candidate.social_urls),
        "aggregators": _json_cell(candidate.aggregator_urls),
        "owned_domains": _json_cell(candidate.owned_domains),
        "brand_name": raw.brand_name or "",
        "is_chain": "true" if candidate.is_chain else "false",
        "chain_reason": candidate.chain_reason or "",
        "confidence": "" if raw.confidence is None else str(raw.confidence),
        "operating_status": raw.operating_status or "",
        "google_place_id": candidate.google_place_id or "",
        "source_refs": _json_cell([ref.model_dump(mode="json") for ref in raw.source_refs]),
    }
    protected: dict[str, str] = {}
    for key, value in row.items():
        if key in {
            "score_reasons",
            "phones",
            "emails",
            "socials",
            "aggregators",
            "owned_domains",
            "source_refs",
        }:
            protected[key] = value
        else:
            protected[key] = protect_formula(value)
    return protected


def sort_candidates(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(
        candidates,
        key=lambda c: (
            -c.score,
            c.distance_m,
            (c.raw.name or "").lower(),
            c.raw.overture_id,
        ),
    )


def preflight_output(paths: OutputPaths, *, overwrite: bool) -> None:
    parent = paths.csv_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Cannot create output directory {parent}: {exc}") from exc

    existing = [p for p in paths.all_final() if p.exists()]
    if existing and not overwrite:
        raise OutputError(
            "Output files already exist (use --overwrite): " + ", ".join(str(p) for p in existing)
        )

    # Same-filesystem check for temp dir vs final parent.
    tmp_probe = parent / f".{paths.stem}.tmp-probe-{uuid.uuid4().hex}"
    try:
        tmp_probe.mkdir()
        if parent.stat().st_dev != tmp_probe.stat().st_dev:
            raise OutputError("Temporary and final output paths are not on the same filesystem")
    except OSError as exc:
        raise OutputError(f"Cannot prepare temp output directory: {exc}") from exc
    finally:
        if tmp_probe.exists():
            shutil.rmtree(tmp_probe, ignore_errors=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    command_parameters: dict[str, Any],
    overture_release: str,
    counts: dict[str, int],
    google: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "started_at": started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "command_parameters": command_parameters,
        "overture_release": overture_release,
        "counts": counts,
        "google": google,
        "warnings": warnings,
        "tool_version": __version__,
        "python_version": sys.version.split()[0],
        "duckdb_version": duckdb.__version__,
        "data_fresh_until": (finished_at + timedelta(days=30))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def write_failed_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_success_bundle(
    paths: OutputPaths,
    *,
    candidates: list[Candidate],
    overture_release: str,
    manifest: dict[str, Any],
    overwrite: bool,
    verify_limit: int = DEFAULT_VERIFY_LINK_LIMIT,
) -> None:
    """Write CSV/manifest/links/complete atomically with optional backup."""
    run_id = str(manifest["run_id"])
    parent = paths.csv_path.parent
    tmp_dir = parent / f".{paths.stem}.tmp-{run_id}"
    backup_dir = parent / f".{paths.stem}.backup-{run_id}"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    tmp_csv = tmp_dir / paths.csv_path.name
    tmp_manifest = tmp_dir / paths.manifest_path.name
    tmp_links = tmp_dir / paths.verify_links_path.name
    tmp_complete = tmp_dir / paths.complete_path.name

    try:
        with tmp_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
            for candidate in candidates:
                writer.writerow(candidate_to_row(candidate, overture_release=overture_release))

        tmp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_links.write_text(
            format_verify_links(candidates, limit=verify_limit),
            encoding="utf-8",
        )

        hashes = {
            paths.csv_path.name: _sha256_file(tmp_csv),
            paths.manifest_path.name: _sha256_file(tmp_manifest),
            paths.verify_links_path.name: _sha256_file(tmp_links),
        }
        complete_payload = {"run_id": run_id, "sha256": hashes}
        tmp_complete.write_text(
            json.dumps(complete_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        backed_up = False
        if overwrite and any(p.exists() for p in paths.all_final()):
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            backup_dir.mkdir()
            for final in paths.all_final():
                if final.exists():
                    final.rename(backup_dir / final.name)
            backed_up = True

        promoted: list[Path] = []
        try:
            for src, dest in (
                (tmp_csv, paths.csv_path),
                (tmp_manifest, paths.manifest_path),
                (tmp_links, paths.verify_links_path),
            ):
                os.replace(src, dest)
                promoted.append(dest)
            os.replace(tmp_complete, paths.complete_path)
            promoted.append(paths.complete_path)
        except OSError as exc:
            for path in promoted:
                path.unlink(missing_ok=True)
            if backed_up:
                for item in backup_dir.iterdir():
                    os.replace(item, parent / item.name)
            raise OutputError(f"Failed to promote output bundle: {exc}") from exc

        if backed_up and backup_dir.exists():
            shutil.rmtree(backup_dir)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
