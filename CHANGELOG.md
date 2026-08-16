# Changelog

## 0.1.0 — 2026-08-16

### Added
- `finder search` over Overture Maps Places (DuckDB GeoParquet + haversine radius)
- Category aliases, domain rules, chain denylist, taxonomy snapshot (schema 1.18.0)
- Deterministic normalize / dedupe / classify / score pipeline
- Atomic CSV + manifest + verify_links + `.complete` marker
- `finder config validate`, `finder overture schema`
- `finder calibration prepare|evaluate|gui` for manual Maps review
- Native Windows / Python 3.12 installation workflow with an offline fixture gate
- MIT `LICENSE` and release packaging contract tests

### Changed
- v1 runtime is Overture-only: no Google Places API, no `--enrich`, no API key, no `.env`
- `latest` falls back to Overture's official public S3 release listing when STAC is unavailable
- Calibration approvals are hash-validated; review CSV rewrites are atomic
- Local review GUI uses CSP/security headers and text-only DOM rendering for external place data
- Search CLI prints every bundle path and `data_fresh_until`

### Notes
- STAC may be unavailable or omit `schema:version`; resolver uses official S3 discovery and the taxonomy snapshot with an explicit warning
- Manual Google Maps search URLs remain for human verification; the backend does not fetch them
