# Attribution and licenses

## Application

Customer Finder is released under the MIT license (see `pyproject.toml`).

## Overture Maps data

Derived place data comes from [Overture Maps Places](https://docs.overturemaps.org/guides/places/).
Before redistributing derived CSVs or screenshots, follow the official
[attribution requirements](https://docs.overturemaps.org/attribution/).

Each successful run stores paired `dataset` / `license` values in the CSV
`source_refs` column and records the Overture release id in the manifest.

## Google Places API (optional)

When `--enrich google` is used, requests go to the official Places API (Text Search New).
Review:

- [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
- [Pricing](https://developers.google.com/maps/billing-and-pricing/pricing)

Do not store raw Google responses, ratings, or website URLs in product outputs.
Only `google_place_id` may be persisted on a lead row.
