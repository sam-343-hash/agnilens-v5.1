# AgniLens architecture
Flask app + SQLite + static pages (Leaflet, Chart.js). No build step.

| Module | Role |
|---|---|
| `harmonize.py` | Pure matching engine (normalise, grid search, haversine, groups). Unit-tested without a database. |
| `db.py` | SQLite connection, versioned migrations (`PRAGMA user_version`), seeded regions. |
| `importer.py` | CSV/JSON/GeoJSON archive import (background thread, progress rows) and live NRT ingestion (one import row per FIRMS source). |
| `analytics.py` | Daily/monthly aggregates, coverage logic, calendar, anomaly scoring, DB-backed harmonization runs. |
| `api.py` | JSON API (blueprint). The FIRMS key is read from the environment and never sent to the browser. |
| `demo_data.py` | Synthetic data (origin `demo`), never mixed with NASA data. |
| `app.py` | App setup, page routes, and the experimental smoke-transport endpoint. |

**Tables:** `satellite_observations` (canonical), `observation_sources` (provenance: every import that reported an observation), `data_imports` (declared `bbox`, `extent_label`, coverage dates and whether they were assumed), `processing_runs`, `harmonization_matches`, `correspondence_groups`, `daily_activity`, `monthly_activity`, `regions`.

**Identity and scope.** Canonical identity is `UNIQUE(scope, sensor, satellite, acq_utc, lat, lon)` with `scope` in `nasa` | `demo`. Imports use `INSERT OR IGNORE`, then link themselves to the canonical row in `observation_sources` (primary key `observation_id, import_id`; cascade delete). Every query is scoped, so synthetic data cannot appear in NASA views or totals.

**Migrations.** `db.MIGRATIONS` is an ordered list tracked with `PRAGMA user_version`. Version 2 rebuilds `satellite_observations` (SQLite cannot change a UNIQUE constraint in place), backfills `scope` from `origin`, backfills provenance from existing rows and adds `extent_label`. Version 3 adds `platform_raw` to canonical observations and provenance. Version 4 adds full source `raw_record` JSON to observations and provenance. Existing databases keep their rows and ids; legacy imports keep an undeclared (NULL) extent and legacy raw source fields remain NULL because the original input was not retained.

**Coverage model.** `analytics.coverage_ranges` returns (start, end, confirmed) only for imports whose declared bbox contains the region. `cov_state` resolves confirmed > assumed > none for a day. The calendar derives `active` / `confirmed_zero` / `assumed_coverage` / `no_data` from it; monthly views and anomaly baselines use confirmed coverage only.

**Scaling path:** indexes on date, sensor+date, scope+date and lat/lon; paginated or thinned map queries; aggregates precomputed after each import. To move to PostgreSQL/PostGIS, replace `db.py`, add a geography column and a GiST index, and keep the same schema.

The browser receives bounded map results (the API reports total count and thinning interval); it never downloads the full observation table. Archive uploads are capped at 50 MiB. A full import currently parses the submitted file in memory, so unusually large archive requests should be split into manageable time periods.
