"""Search pipeline orchestration (single entrypoint for stages)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from customer_finder.classify import classify_place, detect_chains
from customer_finder.deduplicate import deduplicate
from customer_finder.errors import (
    ArgumentError,
    ConfigError,
    CustomerFinderError,
    OutputError,
    OvertureError,
)
from customer_finder.geometry import haversine_m
from customer_finder.models import Candidate, CandidateBucket, SearchRequest
from customer_finder.output import (
    build_manifest,
    derive_output_paths,
    failed_manifest_path,
    preflight_output,
    sort_candidates,
    stale_output_warning,
    write_failed_manifest,
    write_success_bundle,
)
from customer_finder.overture import (
    assert_schema_matches_snapshot,
    fetch_places,
    resolve_release,
)
from customer_finder.scoring import score_candidate
from customer_finder.settings import AppConfig, load_config, validate_category_aliases

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    candidates: list[Candidate]
    manifest: dict[str, Any]
    output_paths: Any
    warnings: list[str] = field(default_factory=list)


def _safe_params(request: SearchRequest) -> dict[str, Any]:
    return {
        "lat": request.lat,
        "lon": request.lon,
        "radius_km": request.radius_km,
        "categories": request.categories,
        "output_path": str(request.output_path),
        "min_score": request.min_score,
        "top": request.top,
        "include_has_site": request.include_has_site,
        "overture_release": request.overture_release,
        "config_dir": str(request.config_dir) if request.config_dir else None,
        "overwrite": request.overwrite,
    }


def run_search(
    request: SearchRequest,
    *,
    parquet_path: str | None = None,
    config: AppConfig | None = None,
) -> PipelineResult:
    """Execute the full search pipeline. Network is skipped when parquet_path is set."""
    started_at = datetime.now(UTC)
    run_id = str(uuid4())
    warnings: list[str] = []
    paths = derive_output_paths(request.output_path)
    failed_path = failed_manifest_path(request.output_path)

    try:
        cfg = config or load_config(request.config_dir)
        validate_category_aliases(request.categories, cfg)
        preflight_output(paths, overwrite=request.overwrite)
        if request.overwrite:
            stale = stale_output_warning(request.output_path)
            if stale:
                warnings.append(stale)

        if parquet_path is None:
            resolved = resolve_release(
                request.overture_release,
                snapshot_schema_version=cfg.taxonomy_snapshot.schema_version,
            )
            assert_schema_matches_snapshot(resolved, cfg)
            warnings.extend(resolved.warnings)
            source_path = resolved.parquet_glob
            release_id = resolved.release_id
        else:
            release_id = request.overture_release
            if release_id == "latest":
                release_id = "fixture"
            source_path = parquet_path

        filtered, query_stats = fetch_places(
            parquet_path=source_path,
            center_lat=request.lat,
            center_lon=request.lon,
            radius_km=request.radius_km,
            aliases=request.categories,
            config=cfg,
            release_id=release_id,
        )
        if (
            query_stats.raw_category_bbox == 0
            and query_stats.bbox_total_diagnostic
            and query_stats.bbox_total_diagnostic > 0
        ):
            warnings.append(
                "bbox has places but category filter returned zero rows; "
                "check taxonomy snapshot vs Overture release"
            )

        places = [place for place, _distance in filtered]

        permanently_closed = sum(
            1 for place in places if place.operating_status == "permanently_closed"
        )
        open_places = [place for place in places if place.operating_status != "permanently_closed"]

        dedup = deduplicate(open_places)
        if dedup.merged_groups:
            logger.info(
                "deduplicated groups=%s",
                [list(group) for group in dedup.merged_groups],
            )

        chain_map = detect_chains(dedup.places, cfg)
        candidates: list[Candidate] = []
        bucket_counts = {
            "has_owned_site": 0,
            "social_only": 0,
            "aggregator_only": 0,
            "likely_no_site": 0,
            "unknown": 0,
        }

        for place in dedup.places:
            classification = classify_place(
                place, config=cfg, chain_info=chain_map[place.overture_id]
            )
            if classification.bucket is None:
                permanently_closed += 1
                continue
            if classification.category_alias is None:
                warnings.append(f"no category alias for {place.overture_id}; skipped")
                continue
            warnings.extend(classification.warnings)
            distance_m = haversine_m(request.lat, request.lon, place.lat, place.lon)

            candidate = score_candidate(
                place,
                config=cfg,
                bucket=classification.bucket,
                category_alias=classification.category_alias,
                is_chain=classification.is_chain,
                chain_reason=classification.chain_reason,
                owned_domains=classification.owned_domains,
                social_urls=classification.social_urls,
                aggregator_urls=classification.aggregator_urls,
                other_urls=classification.other_urls,
                distance_m=distance_m,
            )
            bucket_counts[candidate.bucket.value] += 1
            candidates.append(candidate)

        if not request.include_has_site:
            candidates = [c for c in candidates if c.bucket != CandidateBucket.HAS_OWNED_SITE]

        candidates = [c for c in candidates if c.score >= request.min_score]
        candidates = sort_candidates(candidates)
        if request.top is not None:
            candidates = candidates[: request.top]

        finished_at = datetime.now(UTC)
        counts = {
            "raw_category_bbox": query_stats.raw_category_bbox,
            "inside_radius": query_stats.after_radius,
            "permanently_closed": permanently_closed,
            "deduplicated": dedup.deduplicated_count,
            "has_owned_site": bucket_counts["has_owned_site"],
            "social_only": bucket_counts["social_only"],
            "aggregator_only": bucket_counts["aggregator_only"],
            "likely_no_site": bucket_counts["likely_no_site"],
            "unknown": bucket_counts["unknown"],
            "output": len(candidates),
        }
        if not candidates:
            warnings.append("empty result set")

        manifest = build_manifest(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            command_parameters=_safe_params(request),
            overture_release=release_id,
            counts=counts,
            warnings=warnings,
        )
        write_success_bundle(
            paths,
            candidates=candidates,
            overture_release=release_id,
            manifest=manifest,
            overwrite=request.overwrite,
            verify_limit=request.top or 30,
        )
        return PipelineResult(
            candidates=candidates,
            manifest=manifest,
            output_paths=paths,
            warnings=warnings,
        )
    except (ArgumentError, ConfigError, OvertureError, OutputError) as exc:
        finished_at = datetime.now(UTC)
        payload = build_manifest(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            command_parameters=_safe_params(request),
            overture_release=request.overture_release,
            counts={},
            warnings=[*warnings, exc.message],
        )
        payload["error"] = {"type": type(exc).__name__, "message": exc.message}
        try:
            write_failed_manifest(failed_path, payload)
        except OSError:
            logger.exception("failed to write failed manifest")
        raise
    except Exception as exc:
        finished_at = datetime.now(UTC)
        payload = build_manifest(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            command_parameters=_safe_params(request),
            overture_release=request.overture_release,
            counts={},
            warnings=warnings,
        )
        # Do not persist str(exc): unexpected errors (e.g. httpx) can include headers/secrets.
        payload["error"] = {"type": type(exc).__name__, "run_id": run_id}
        try:
            write_failed_manifest(failed_path, payload)
        except OSError:
            logger.exception("failed to write failed manifest")
        raise CustomerFinderError(f"Unexpected error (run_id={run_id})") from exc
