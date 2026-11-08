# Engineering audit

Audit date: 2026-11-08. Scope: application source, tests, project documentation and static frontend in this repository.

## Findings and fixes

- Query parameter parsing accepted permissive or non-finite numbers and could fail indirectly on partial or malformed dates. Date parsing now requires ISO calendar dates, numeric values must be finite, integer/year inputs are validated, and paired date ranges are enforced where required.
- Overview counts and import summaries could include observations outside the selected region. Region bounds now scope those counts and import results.
- Map thinning sampled by global row IDs, which could yield too few or zero points for a filtered subset. Sampling now ranks the matched result set before thinning.
- Unbounded/very large date requests and simultaneous import launches could consume substantial CPU or memory. Date-span limits and a two-job import semaphore now bound these requests; a saturated queue returns a retryable 429.
- Import file errors were difficult to diagnose. JSON/GeoJSON structure and required CSV columns are checked before records are normalized, and upload-size errors return JSON with the configured limit.
- Unexpected worker launch/runtime failures now produce a failed import state rather than silently leaving no useful error; import filenames use `secure_filename`.
- UI error and busy states, region data escaping, empty-state onboarding and keyboard access have been improved (see `UI_UX_AUDIT.md`).

## Reviewed behavior retained

The existing code keeps separate NASA/demo scopes, canonical exact duplicate identity with per-import provenance, versioned SQLite migrations, declared rather than inferred geographic coverage, coverage-quality states, UTC matching, many-to-many match groups, confirmed-coverage anomaly baselines, bounded map responses, and explicitly experimental smoke transport. No synthetic observations were added to NASA scope, no historical database rows were deleted, and no candidate pair is promoted to a verified fire.

## Architecture and limits

Flask serves static HTML/JavaScript and a JSON API; SQLite stores observations, provenance, imports, coverage, runs and match groups. The harmonization engine remains in `harmonize.py`. Archive uploads are parsed in memory and capped at 50 MiB. Import workers are in-process daemon threads and their job state is in SQLite; after process restart, a job interrupted mid-run may remain marked running. The semaphore limits concurrent imports but does not provide durable job recovery. This is a remaining operational limitation.

Shapefiles remain unsupported; CSV, JSON and GeoJSON are supported. Archive files are trusted as user-supplied inputs; the app cannot independently prove NASA provenance. Live FIRMS requests and credentials were not exercised against NASA during this audit. The request key stays server-side and error URL redaction is covered by tests. No live archive data was supplied, so there are no file hashes, sensor coverage records, matching distributions or scientific accuracy estimates to report.

## Security/performance review

- SQL values in the reviewed API paths are parameterized; dynamic table/query parts are selected from internal allowlists.
- Uploaded HTML is not served or rendered. Import history strings and region names are escaped before frontend insertion; the experimental transport label was corrected to avoid implying that satellite observations directly measure smoke transport.
- Response sizes are bounded for map queries, upload size is limited, import concurrency is bounded, and harmonization has a record-count guard.
- SQLite work remains synchronous, and uploads are parsed in memory. Large operational archive workloads should be split into smaller periods; a durable queue and streaming parser would be appropriate future work.
- CDN-backed Leaflet and Chart.js use local failure messages/fallbacks where present; live CDN outage behavior was not simulated in a browser during this audit.

## Verification

`TEST_RESULTS.md` records the full 86-test pass. Browser inspection opened all ten routed pages at `http://127.0.0.1:5001/`; each returned its expected heading and no browser-console errors were observed during initial rendering. This was a route/render smoke check, not a full interaction E2E run. See `MANUAL_QA_GUIDE.md` for steps that require live data or broader manual interaction.
