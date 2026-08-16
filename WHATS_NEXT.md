# What's next — Customer Finder

**Last updated:** 2026-08-16
**Branch:** `calibration-review-gui` (on top of the cloud-agent MVP + audit fixes)

---

## Where we are

| Milestone | Status |
|-----------|--------|
| 0 — Skeleton | Done |
| 1 — Models & config | Done |
| 2 — Geometry & Overture | Done (live works; STAC schema fallback) |
| 3 — Candidate quality | Done |
| 4 — Output & full CLI | Done |
| 5 — Calibration (Wrocław) | Done — gate passed, approval valid |
| 6 — API-free hardening | Done — no Places API path in the supported runtime |
| **7 — Docs & release v0.1.0** | **Done — native Windows release gates passed** |

Decision for v1: no commercial API key, no Google Places API calls. Google Maps
links remain only for user-initiated manual verification in the localhost review desk.

---

## Manual checklist (do in order)

### 1. Milestone 5 — completed

- `out/calibration.approved.json` exists and its hashes validate.
- Top 20: `target_precision = 0.80`.
- Top 20: `no_site_precision = 0.75`.
- Full calibration: 30/30 complete.
- Live Overture run: 23.2 seconds on release `2026-07-22.0`.

---

### 2. Milestone 6 — API-free hardening — completed

Do not create a Google API key and do not run a Google smoke test.

Implementation work:

- [x] Remove `--enrich google`, `--google-max-requests` and Google-only strict behavior from the public CLI contract.
- [x] Remove or hard-disable production calls to Google Places API.
- [x] Remove `google_place_id` and Google aggregates from the v1 CSV/manifest contract.
- [x] Remove `google-calibration` commands from the supported v1 workflow.
- [x] Keep ordinary Maps search URLs and the manual calibration GUI.
- [x] Update README and CLI help; remove the now-unneeded `.env.example`.
- [x] Add a regression test proving the standard backend never calls Google hosts.
- [x] Run Ruff, mypy, all offline tests and one pinned-release Overture smoke.

M6 passes when `finder search` works from a clean environment without `.env` or
commercial credentials and no supported runtime path can call Google Places API.

---

### 3. Milestone 7 — release tag

After M6 passes:

- [x] Confirm README / ATTRIBUTION / CHANGELOG look right
- [x] Pass a clean Python 3.12 installation and offline fixture search
- [x] Pass Ruff, format, mypy and tests (117 passed, 1 deselected, 88% coverage)
- [x] Pass a browser GUI smoke test with no external requests or console errors
- [x] Pass live `latest`: 194 rows from release `2026-07-22.0`
- [x] Audit live top 20: zero post-dedup conflicts, chain ratio 0%, valid bundle hashes
- [x] Validate the approved calibration hashes (`target_precision=0.80`, `no_site_precision=0.75`)
- [x] Package `LICENSE` and the static GUI in a clean wheel; no forbidden runtime packages
- [x] Pass a native Windows offline fixture search without Docker or WSL (18 rows)
- [x] Review and commit the current implementation changes
- [x] Apply tag `v0.1.0` to the release commit

---

## What you can ignore for now

- `out/*` is gitignored (except `.gitkeep`) — leads/calibration stay local
- Live STAC may be unavailable or omit `schema:version`; the app discovers the
  latest retained release from Overture's official public S3 listing and uses
  taxonomy snapshot `1.18.0` with an explicit warning (plan §9.1)

---

## Quick status one-liner

**Milestones 0–7 passed; v0.1.0 uses native Python 3.12 on Windows.**
