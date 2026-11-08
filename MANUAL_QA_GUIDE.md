# Manual QA guide

## Browser smoke check performed

On 2026-11-08, the local app at `http://127.0.0.1:5001` was opened in the Codex in-app browser. Overview, Data, Harmonization, Calendar, Map, MODIS vs VIIRS, Anomalies, Regions, Reports and Experimental each rendered a page heading; no console errors were present during the initial route check. Overview displayed the three onboarding routes and separate NASA/demo scope notice. A screenshot of this actual page was captured in the task session. This check did not submit forms or mutate the local database.

## Repeatable manual journeys

1. **First use:** open Overview; follow Import archive to Data; verify file format guidance, scope banner, extent and coverage controls, status and import history. Return to Overview and use the demo route only if you intend to seed demo-scope data.
2. **Demo isolation:** on Data, load demo; select Demo scope; inspect Overview, Map, Calendar and Reports; switch back to NASA and confirm demo records are absent. Use Clear demo only when you intend to remove demo data.
3. **Archive import:** prepare a FIRMS CSV, JSON or GeoJSON; choose sensor/extent and actual coverage period; submit once; observe busy state and final accepted/duplicate/rejected counts. Try malformed JSON and a file exceeding 50 MiB; expect a clear failure message and no partial import.
4. **Harmonization:** with both MODIS and VIIRS records in one scope, select a bounded period, adjust distance/time cutoffs, run once and inspect counts and candidate-pair caveat. Try a range above the supported limit; expect validation instead of a stalled run.
5. **Calendar and anomalies:** inspect active, confirmed-zero, assumed-coverage and no-data states. Confirm assumed coverage is visibly distinguished and excluded from anomaly baselines. Check behavior with fewer than three comparable years.
6. **Map:** try each sensor/layer option, date filters and region. Verify legend matches visible layer and the map reports when no observations match.
7. **Reports:** choose a valid period and export CSV and HTML; verify selected region, period and scope. Try missing/partial dates and ensure export controls remain unavailable.
8. **Keyboard/responsive:** navigate from the skip link with Tab/Enter/Space; activate calendar days and experimental hour controls from keyboard; test at a narrow viewport and browser zoom.
9. **Live NASA (optional):** configure a server-side FIRMS map key, request a small NRT window, verify failed source status is distinct from zero records, and confirm the key does not appear in browser HTML, API JSON or errors.

## Test boundaries

Automated fixtures cover API routes, validation, parsing, persistence/migrations, provenance, harmonization, coverage, calendar/anomaly calculations and exports. The complete list and outcomes are in `TEST_RESULTS.md`. No live FIRMS data was requested and no real archive was present; the journeys above that require real data remain operator-run checks. Do not interpret synthetic fixtures as scientific validation.
