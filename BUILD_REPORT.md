# AgniLens V5.1 build report: audit and current verification

The attached ZIP's previous report described a V5.1 patch and claimed 72 passing tests. Those numbers are historical claims from the supplied report; the current working copy was independently re-run below and reports its own results.

## What changed (targeted; no rebuild)
| # | Issue | Fix |
|---|---|---|
| 1 | Imports without an extent counted as covering every region | Archive imports **require** a declared extent (Punjab, Haryana, Punjab + Haryana, India, custom box; validated), stored in `data_imports.bbox` + `extent_label`. Coverage applies only to regions fully inside it. Undeclared extent gives no regional coverage. Import history shows the extent. `POST /api/imports/<id>/extent` declares one for older imports. |
| 2 | `UNIQUE(sensor,satellite,acq_utc,lat,lon)` collided demo and NASA, and archive/NRT repeats | Canonical identity now includes `scope` (`nasa`/`demo`). New `observation_sources` table links every contributing import (with its own version, confidence, FRP). Repeats are counted once. Migration v2 upgrades existing databases in a transaction. |
| 3 | Assumed coverage looked like confirmed zero | Day states `active` / `confirmed_zero` / `assumed_coverage` / `no_data`. Assumed days have no intensity, are drawn differently, produce warnings, and are excluded from monthly baselines and anomaly scoring. Reports state the counts. |
| 4 | Platform check compared only counts | Platform **identities** compared per month (Jaccard similarity, added/missing platforms, heterogeneous-baseline warning). Per-sensor and per-platform counts kept. |
| 5 | `normalize()` rounded coordinates to 4 decimals for duplicates | Duplicate identity uses full source precision (and satellite). |

## Hotfix (V5.1.1): pages loaded without styling
A route added in V5 (`/<page>`) shadowed the static handler, so `/shared.css` and `/shared.js` returned 404 and every page rendered as unstyled HTML with no navigation or data. Fixed in `app.py`; a new test now requests every local CSS/JS file referenced by any page and checks it is served (and that unknown files and path traversal return 404). The V5 test suite missed this because it only checked that pages returned 200. Verified against a live server with curl.

## Existing tests changed (intent preserved)
Four of the original 39 tests were edited because behaviour deliberately changed; nothing was deleted:
`test_zero_vs_no_data_and_monthly` (declares an extent; status renamed `zero` → `confirmed_zero`), `test_persistence_and_idempotent_migration` (schema version is now `len(MIGRATIONS)`), `test_upload_then_query_and_export` (upload now sends the required extent), `test_platform_change_caveat` (platform input is now per-platform counts, not an integer).

## Known limitations
- Region boxes are approximate and overlap; no administrative boundaries.
- Coverage is represented at sensor/import level, not as a per-platform per-pixel observation-quality mask; the platform-set check only sees platforms that produced detections.
- Older imports need an extent declared before they give regional coverage.
- When two sources report the same detection, the observation shows the first source's values; the other sources' values are in the provenance table.
- Shapefile import, custom drawn areas and PDF generation are still missing. The experimental smoke-transport page is an unvalidated heuristic and should not be used operationally.

## ZIP audit and implementation update

The supplied source tree is preserved as an extracted working copy. The original ZIP was not modified. The implementation already had persistent SQLite storage, NRT and historical imports, MODIS/VIIRS candidate matching, four calendar coverage states, monthly platform summaries, median/MAD anomalies, reports, and a static interactive UI. Review of source code showed these behaviors are software features; the project had no real-data validation result.

Changes made in this update:

- Added schema migrations v3 and v4: canonical and per-source provenance now retain normalized and raw satellite labels plus the complete input record JSON. Existing database rows are retained; old rows cannot recover raw fields that were discarded before these migrations.
- Normalized Suomi-NPP, NOAA-20 and NOAA-21 aliases including `SNPP`, `S-NPP`, `NOAA20`, `N20`, `J1`, `NOAA21`, `N21`, and `J2`, preserving the original spelling.
- Validate NASA FIRMS CSV response columns before import, so error text is recorded as source failure rather than a successful empty response. NRT results expose import IDs and retrieval timestamps; the experimental page reports partial source failures, synthetic fallback and cached retrieval time.
- Load ignored local `.env` settings without an added dependency, preserve shell-variable precedence, restrict the configured file to owner read/write, and redact MAP_KEY values from returned request errors.
- Scope report source totals to the selected region, keep monthly rows inside the requested period, and include contributing imports, coverage, retrieval timestamps and overlapping harmonization run parameters in CSV/HTML exports.
- Validate map bounding boxes and upload extensions; cap uploads at 50 MiB; remove the conditional debug-information endpoint and disable Flask debug mode by default.
- Add `validate_archive_pair.py` for reproducible record accounting, platform/date summaries, daily counts, and candidate-match sensitivity at several distance/time cutoffs.
- Add `.env.example`, `.gitignore`, `docs/DATA_DICTIONARY.md`, and `docs/SCIENTIFIC_VALIDATION.md`; update setup, methodology, architecture and build notes.
- Add regression tests for platform aliases/raw provenance, error CSV rejection, malformed map bounds and upload extensions.

## Current verification

`python3` is available; the project has no standalone `python` command in this environment. An isolated `.venv` was created inside the working copy and the declared Flask/requests dependencies installed there.

Latest test run: `python -m unittest discover -s tests` from the project directory (using `.venv-clean/bin/python`): **78 tests, OK**. Existing tests emit `ResourceWarning` for unclosed fixture/test-client file handles; these did not fail the suite. Database migration tests cover upgrading legacy schemas; provenance, report scoping, archive sensitivity and MAP_KEY redaction have regression coverage.

Real NASA archive comparison remains pending: no archive files or FIRMS MAP_KEY were supplied. No live ingestion result or scientific accuracy claim is made. See `docs/SCIENTIFIC_VALIDATION.md` for the repeatable experiment and evidence limits.
