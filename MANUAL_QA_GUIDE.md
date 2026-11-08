# Manual QA guide

## Browser checks performed

On 2026-11-08, the redesign was opened at http://127.0.0.1:5002 against an isolated temporary SQLite database containing 13 clearly synthetic demo observations; the user local database was not touched. Overview, Global Map, Harmonization, Data Explorer, Calendar, Compare, Anomalies, Regional Analytics, Reports and Experimental rendered with the shared sidebar and the expected active link. No browser console errors were present after correcting an Experimental-page map variable collision.

On Overview, the NASA scope showed an empty state while the demo scope showed demo-labeled counts, a timeline and clustered map observations. The 24-hour and custom date ranges updated the chart/map; toggling sensor filters updated the totals; the heat layer could be enabled; Reset returned to the default 30-day view. The desktop sidebar collapsed to 76 pixels and expanded again. Actual desktop screenshots were captured in the task session.

Responsive browser checks were performed at 1440×900, 1024×900, 768×900 and 390×844. At each width, the document and body stayed within the viewport width; at 390 pixels the main content was 390 pixels and the map was 362 pixels. The mobile menu opened the drawer, and Escape closed it and reset aria-expanded. This manual check did not submit archive/NASA forms or mutate the user local database.

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
