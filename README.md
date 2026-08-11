# Customer Finder

CLI that searches Overture Maps Places for local cafes, bakeries, pastry shops,
and ice cream shops that likely do not have an owned website.

## Implementation status

| Milestone | Status | Notes |
|-----------|--------|-------|
| **0–4** | **Done** | Full offline + live Overture search CLI |
| **5 — Calibration** | **Awaiting you** | Live Wrocław run done; fill `out/calibration.csv` |
| **6 — Google enrichment** | **Code done (gated)** | Requires `out/calibration.approved.json` + `GOOGLE_MAPS_API_KEY` |
| **7 — Docs** | **Mostly done** | CHANGELOG + ATTRIBUTION; tag v0.1.0 after calibration |

## Your calibration steps (do this when ready)

```powershell
# If needed, regenerate leads + empty review sheet:
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream --enrich none `
  --output out/leads_wroclaw.csv --overwrite
finder calibration prepare --leads out/leads_wroclaw.csv `
  --output out/calibration.csv --limit 30 --overwrite

# Fill ALL five fields for every row in out/calibration.csv:
#   entity_status: valid | wrong_entity | uncertain
#   target_category: yes | no | uncertain
#   operating_status_review: open | closed | uncertain
#   independence: independent | chain | uncertain
#   site_status: no_owned_site | owned_site | social_only | uncertain
# Use google_maps_url in each row. Partial rows are rejected.

finder calibration evaluate `
  --file out/calibration.csv `
  --output out/calibration.summary.json
```

Pass when top20 `target_precision >= 0.80`, `no_site_precision >= 0.70`, and all 30 rows are complete. That writes `out/calibration.approved.json`.

Then Google enrich:

```powershell
# .env: GOOGLE_MAPS_API_KEY=...
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --enrich google --google-max-requests 50 `
  --output out/leads_wroclaw_google.csv
```

## Quick start

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

Offline fixture (no network):

```powershell
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --overture-release fixture `
  --parquet tests/fixtures/overture_places.parquet `
  --output out/leads_fixture.csv
```

Requires Python 3.12.

## Docker

```powershell
docker build -t customer-finder .
docker run --rm -v "${PWD}/out:/app/out" customer-finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --output /app/out/leads.csv
```

## Google cost warning

`--enrich google` calls Places Text Search (New). Field mask includes `websiteUri`,
which can affect SKU/cost. Set a low `--google-max-requests` budget. See
[Google Maps pricing](https://developers.google.com/maps/billing-and-pricing/pricing).
Google never changes permanent buckets/scores; only `google_place_id` may be stored.

## Buckets

| Bucket | Meaning |
|--------|---------|
| `likely_no_site` | No owned domain / social / aggregator found in sources used |
| `social_only` | Only social profiles found |
| `aggregator_only` | Only aggregator links found |
| `unknown` | Insufficient / ambiguous data |
| `has_owned_site` | Owned domain found (excluded unless `--include-has-site`) |

`likely_no_site` means no owned domain was found in the sources used — not proof a site does not exist.

## Data freshness

Manifest `data_fresh_until` = finished_at + 30 days. Delete stale `out/<stem>.*` and re-run on a current Overture release.

## License / attribution

See `ATTRIBUTION.md`. Primary data: [Overture Maps Places](https://docs.overturemaps.org/guides/places/).
