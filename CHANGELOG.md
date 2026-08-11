# Changelog

## 0.1.0 (unreleased)

### Added
- `finder search` over Overture Maps Places (DuckDB GeoParquet + haversine radius)
- Category aliases, domain rules, chain denylist, taxonomy snapshot (schema 1.18.0)
- Deterministic normalize / dedupe / classify / score pipeline
- Atomic CSV + manifest + verify_links + `.complete` marker
- `finder config validate`, `finder overture schema`
- `finder calibration prepare|evaluate` and `finder google-calibration prepare|evaluate`
- Optional `--enrich google` (Places Text Search New), gated on `calibration.approved.json`
- Dockerfile (`python:3.12-slim`, non-root)

### Notes
- STAC currently may omit `schema:version`; resolver falls back to taxonomy snapshot with a warning
- Google enrichment does not change buckets/scores; only `google_place_id` may be persisted
