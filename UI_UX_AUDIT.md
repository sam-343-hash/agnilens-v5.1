# UI/UX audit

## Changes made

- The overview now gives first-use choices for live NASA NRT, archive import and synthetic demo exploration, and states that the data scopes are separate.
- Shared navigation now provides a labeled icon sidebar with active-page state, desktop collapse/expand, an accessible small-screen drawer, shared scope/region filters, a skip link and visible keyboard focus.
- Overview is redesigned as a monitoring dashboard with period KPIs, a real observation timeline, dataset-scope indicator, controls, Leaflet map, map layers, clustering and a heat layer.
- Timeline presets (24 hours, 7, 30 and 90 days, or custom) are linked to the dashboard map and KPIs. Gaps without confirmed coverage remain gaps; missing detections are not filled in as zeros.
- High-confidence series are visibly defined as MODIS raw confidence ≥80 and VIIRS raw h/high, with a note that these sensor scales are not equivalent.
- Shared helpers escape region names, show a useful network failure, and disable/mark operations busy while requests are in progress.
- Data import removes repeated submit logic, validates required selections, reports failures, caps polling, safely renders import history and confirms before clearing demo data.
- Map controls now have linked labels, accessible status/legend text, an accessible map name, loading state and an explanation when Leaflet is unavailable.
- Calendar day cells support keyboard activation; the monthly plot displays the sensor series as separate values and explains when Chart.js is unavailable.
- Harmonization, comparison, anomalies and regional analysis expose busy/error states; chart failure and incomplete baseline cases are communicated.
- Reports enforce a complete date period before enabling exports and open generated HTML safely in a new tab.
- Experimental transport wording now describes satellite detections rather than implying measured smoke trajectories. Its hour controls are keyboard accessible and library failure is visible.

## Remaining opportunities

- The shared color palette and dense data tables can benefit from a dedicated contrast audit with automated tooling and assistive-technology review.
- Browser checks at 1440, 1024, 768 and 390 pixels showed no horizontal document overflow; the 390-pixel drawer opened and closed with Escape. The mobile top-bar title and selected region text truncate to fit, while their accessible labels and full select options remain available.
- Several pages remain information-dense. A focused usability review with challenge participants would validate terminology, task order and whether the technical caveats are discoverable.
- No formal WCAG conformance claim is made. Browser smoke inspection is not a substitute for screen-reader, zoom, contrast and mobile-device testing.
