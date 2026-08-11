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
| 2 — Geometry & Overture | Next | bbox/haversine, STAC, DuckDB, fixture parquet |
| 3 — Candidate quality | Pending | normalize, dedupe, chains, buckets, scoring |
| 4 — Output & full CLI | Pending | pipeline, CSV/manifest/atomic write, README |
| 5 — Calibration (Wrocław) | Pending | Human-reviewed calibration gate |
| 6 — Google enrichment | Pending | Only after calibration.approved.json |
| 7 — Docs & v0.1.0 | Pending | |

**Cloud agent start here:** Milestone 2. Install with `pip install -e ".[dev]"`,
then run the quality gate from plan §19.4 before marking any milestone complete.

## Quick start (local / cloud)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
finder version
ruff format --check .
ruff check .
mypy src
pytest -q
```

Requires Python 3.12.

## License / attribution

Data source: [Overture Maps Places](https://docs.overturemaps.org/guides/places/).
See Overture attribution requirements before redistributing derived data.
