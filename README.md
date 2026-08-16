# Customer Finder

CLI that searches Overture Maps Places for local cafes, bakeries, pastry shops,
and ice cream shops that likely do not have an owned website.

v0.1.0 is Overture-only. Installation and search do not require a commercial API
key or a `.env` file. The app never calls Google Places API. Google Maps links
are generated for manual review only; the backend does not fetch them.

## Implementation status

| Milestone | Status | Notes |
|-----------|--------|-------|
| **0–5** | **Done** | Search CLI + Wrocław calibration gate passed |
| **6 — API-free hardening** | **Done** | No Google Places API path in the supported runtime |
| **7 — Docs & release v0.1.0** | **Done** | Native Windows install and all release gates passed |

## Quick start

Install once:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
```

Then perform the first real search with one command:

```powershell
finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --output out/leads_wroclaw.csv
```

Optional installation checks:

```powershell
finder version
finder config validate
```

Offline fixture (no network):

```powershell
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --overture-release fixture `
  --parquet tests/fixtures/overture_places.parquet `
  --output out/leads_fixture.csv
```

Requires Python 3.12. Docker, WSL and Node.js are not required. The project and
its virtual environment may live entirely on a non-system drive such as `D:`.

For development only, install the editable package with quality tools:

```powershell
pip install -e ".[dev]"
```

## Using the lead list

The CSV is sorted by score, highest first. Start with `likely_no_site`, then
review `social_only` and `aggregator_only`. Use the phone, email and social
columns to plan outreach, but open the corresponding URL from
`<stem>.verify_links.txt` before contacting a business: the bucket is a lead
signal, not proof that the business has no website.

The manifest records filters, counts, duration, Overture release and freshness.
The `.complete` marker contains hashes proving that the CSV, manifest and link
file belong to one fully written run.

## Manual verification

Each successful search writes `<stem>.verify_links.txt` with ordinary Google Maps
search URLs (name + address + locality). Open them yourself in a browser. The
program does not scrape Maps.

Local review desk for calibration:

```powershell
finder calibration gui
```

Then:

```powershell
finder calibration evaluate `
  --file out/calibration.csv `
  --output out/calibration.summary.json
```

Pass when top20 `target_precision >= 0.80`, `no_site_precision >= 0.70`, and all
prepared rows are complete. That writes `out/calibration.approved.json`.

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
