# Attribution and licenses

## Application

Customer Finder is released under the MIT license (see `LICENSE`).

## Overture Maps data

Derived place data comes from [Overture Maps Places](https://docs.overturemaps.org/guides/places/).
Before redistributing derived CSVs or screenshots, follow the official
[attribution requirements](https://docs.overturemaps.org/attribution/).

Each successful run stores paired `dataset` / `license` values in the CSV
`source_refs` column and records the Overture release id in the manifest.

## Manual Google Maps links

The tool may generate ordinary Google Maps search URLs so a person can open a
listing in a browser. Customer Finder does not call Google Places API, does not
fetch Maps pages, and does not store Google place identifiers or API payloads.
