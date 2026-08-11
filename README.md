# Customer Finder

CLI that searches Overture Maps Places for local cafes, bakeries, pastry shops,
and ice cream shops that likely do not have an owned website.

## Implementation status (handoff)

Follow `IMPLEMENTATION_PLAN.md` sequentially. Do not skip milestones or change
non-negotiable architecture decisions without owner approval.

| Milestone | Status | Notes |
|-----------|--------|-------|
| **0 — Skeleton** | **Done** | Package layout, Typer CLI `version`, pyproject, gitignore, tests scaffold |
| **1 — Models & config** | **Done** | Pydantic models, YAML configs (schema 1.18.0), `finder config validate` |
| **2 — Geometry & Overture** | **Done (offline)** | bbox/haversine, STAC/DuckDB, fixture parquet. Live STAC `schema:version` is null — see PR |
| **3 — Candidate quality** | **Done** | normalize, dedupe, chains, buckets, scoring |
| **4 — Output & full CLI** | **Done** | pipeline, CSV/manifest/atomic write, Docker, `finder search` |
| **5 — Calibration (Wrocław)** | **Awaiting human review** | Live 3 km search OK (~5.5s, release 2026-07-22.0). `out/calibration.csv` prepared (30 rows). Fill reviews, then `finder calibration evaluate`. |
| 6 — Google enrichment | Pending | Only after `out/calibration.approved.json` |
| 7 — Docs & v0.1.0 | Pending | |

### Live run (2026-08-11)

```text
release=2026-07-22.0  duration≈5.5s
raw_category_bbox=432  inside_radius=419  output=196
buckets in CSV: social_only=185, unknown=7, likely_no_site=4
(has_owned_site=220 excluded by default)
```

STAC still omits `schema:version`; resolver falls back to taxonomy snapshot `1.18.0` with a manifest warning.

### Human calibration steps

```powershell
# already generated after live search:
#   out/leads_wroclaw.csv
#   out/calibration.csv  (30 empty review rows)

# 1) Open each google_maps_url in out/calibration.csv
# 2) Fill entity_status, target_category, operating_status_review,
#    independence, site_status (all five required per row)
# 3) Evaluate:
finder calibration evaluate `
  --file out/calibration.csv `
  --output out/calibration.summary.json
```

Gates: top20 `target_precision >= 0.80` and `no_site_precision >= 0.70`, all prepared rows complete.

## Quick start (local)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
finder version
finder config validate
finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --enrich none `
  --output out/leads_wroclaw.csv
```

Offline fixture smoke (no network):

```powershell
finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --overture-release fixture `
  --parquet tests/fixtures/overture_places.parquet `
  --output out/leads_fixture.csv
```

Requires Python 3.12.

## Docker

```powershell
docker build -t customer-finder .
docker run --rm `
  -v "${PWD}/out:/app/out" `
  customer-finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --output /app/out/leads.csv
```

## Quality gate

```powershell
ruff format --check .
ruff check .
mypy src
pytest -q --cov=customer_finder --cov-report=term-missing
```

## Buckets

| Bucket | Meaning |
|--------|---------|
| `likely_no_site` | No owned domain / social / aggregator found in sources used |
| `social_only` | Only social profiles found |
| `aggregator_only` | Only aggregator links found |
| `unknown` | Insufficient / ambiguous data |
| `has_owned_site` | Owned domain found (excluded from CSV unless `--include-has-site`) |

`likely_no_site` means: in the sources used, no owned domain was found — not a proof that a site does not exist.

## Data freshness

Each successful run writes `data_fresh_until` (finished_at + 30 days) in the
manifest. Older result sets should be regenerated against a current Overture
release; delete stale `out/<stem>.*` files manually.

## License / attribution

Data source: [Overture Maps Places](https://docs.overturemaps.org/guides/places/).
See Overture attribution requirements before redistributing derived data.
