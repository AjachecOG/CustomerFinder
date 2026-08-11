# What's next — Customer Finder

**Last updated:** 2026-08-11  
**Branch / PR:** `cursor/milestone-1-models-config-13dc` → [#1](https://github.com/AjachecOG/CustomerFinder/pull/1)

---

## Where we are

| Milestone | Status |
|-----------|--------|
| 0 — Skeleton | Done |
| 1 — Models & config | Done |
| 2 — Geometry & Overture | Done (live works; STAC schema fallback) |
| 3 — Candidate quality | Done |
| 4 — Output & full CLI | Done |
| **5 — Calibration (Wrocław)** | **YOU ARE HERE — needs your manual review** |
| 6 — Google enrichment | Code done, **blocked** until `out/calibration.approved.json` |
| 7 — Docs & release v0.1.0 | Docs mostly done; **tag after** M5 (+ optional Google smoke) |

**Code is effectively complete.** The remaining blockers are human calibration (required) and optional live Google smoke + git tag.

---

## Manual checklist (do in order)

### 1. Milestone 5 — fill calibration reviews

Files already prepared (or regenerate if missing):

- `out/leads_wroclaw.csv` — live 3 km Wrocław search
- `out/calibration.csv` — 30 empty review rows with Maps links

**Regenerate if needed:**

```powershell
pip install -e ".[dev]"
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream --enrich none `
  --output out/leads_wroclaw.csv --overwrite

finder calibration prepare --leads out/leads_wroclaw.csv `
  --output out/calibration.csv --limit 30 --overwrite
```

**For every row in `out/calibration.csv`, open `google_maps_url` and fill all five fields:**

| Field | Allowed values |
|-------|----------------|
| `entity_status` | `valid` \| `wrong_entity` \| `uncertain` |
| `target_category` | `yes` \| `no` \| `uncertain` |
| `operating_status_review` | `open` \| `closed` \| `uncertain` |
| `independence` | `independent` \| `chain` \| `uncertain` |
| `site_status` | `no_owned_site` \| `owned_site` \| `social_only` \| `uncertain` |

Notes:

- All five must be filled if any is filled (no partial rows).
- Prefer `owned_site` over `social_only` when both apply.
- Do **not** leave blanks and assume “no site”.

**Then evaluate:**

```powershell
finder calibration evaluate `
  --file out/calibration.csv `
  --output out/calibration.summary.json
```

**Pass criteria:**

- All 30 prepared rows complete
- Top 20: `target_precision >= 0.80`
- Top 20: `no_site_precision >= 0.70` (`site_status` in `no_owned_site` or `social_only` among valid independents)

On pass, this creates **`out/calibration.approved.json`**. Keep that file; Google enrich checks its hash against the CSV.

---

### 2. Milestone 6 — optional Google smoke (after approval)

1. Put key in `.env` (never commit it):

   ```text
   GOOGLE_MAPS_API_KEY=your_key_here
   ```

2. Run a small enrich (budget is HTTP attempts, including retries):

```powershell
finder search --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --enrich google --google-max-requests 10 `
  --output out/leads_wroclaw_google.csv
```

3. If you get ≥10 rows with `google_place_id`, optionally review matches:

```powershell
finder google-calibration prepare `
  --leads out/leads_wroclaw_google.csv `
  --output out/google-match-review.csv --limit 10

# Fill same_entity = yes | no | uncertain for each row, then:
finder google-calibration evaluate `
  --file out/google-match-review.csv `
  --output out/google-match-review.summary.json
```

Gate for Google match review: **10/10 `yes`** (no `uncertain`).

---

### 3. Milestone 7 — release tag

After M5 passes (and ideally Google smoke if you care about enrich):

- [ ] Confirm README / ATTRIBUTION / CHANGELOG look right
- [ ] Merge PR #1
- [ ] Tag `v0.1.0` on the merged commit

---

## What you can ignore for now

- `out/*` is gitignored (except `.gitkeep`) — leads/calibration stay local
- Live STAC `schema:version` is still null; the app falls back to taxonomy snapshot `1.18.0` with a warning — fine until Overture fixes STAC

---

## Quick status one-liner

**Paused on Milestone 5 human calibration → fill `out/calibration.csv` → `finder calibration evaluate` → then Google (M6) and tag v0.1.0 (M7).**
