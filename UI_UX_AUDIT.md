# UI/UX audit

## Changes made

- The overview now gives first-use choices for live NASA NRT, archive import and synthetic demo exploration, and states that the data scopes are separate.
- Shared navigation adds a skip link, a semantic navigation landmark, selected-page state and horizontal scrolling at narrow widths. Keyboard focus is more visible.
- Shared helpers escape region names, show a useful network failure, and disable/mark operations busy while requests are in progress.
- Data import removes repeated submit logic, validates required selections, reports failures, caps polling, safely renders import history and confirms before clearing demo data.
- Map controls now have linked labels, accessible status/legend text, an accessible map name, loading state and an explanation when Leaflet is unavailable.
- Calendar day cells support keyboard activation; the monthly plot displays the sensor series as separate values and explains when Chart.js is unavailable.
- Harmonization, comparison, anomalies and regional analysis expose busy/error states; chart failure and incomplete baseline cases are communicated.
- Reports enforce a complete date period before enabling exports and open generated HTML safely in a new tab.
- Experimental transport wording now describes satellite detections rather than implying measured smoke trajectories. Its hour controls are keyboard accessible and library failure is visible.

## Remaining opportunities

- The shared color palette and dense data tables can benefit from a dedicated contrast audit with automated tooling and assistive-technology review.
- Navigation scroll affordance could be more obvious on touch devices, especially when the viewport shows only part of the destinations.
- Several pages remain information-dense. A focused usability review with challenge participants would validate terminology, task order and whether the technical caveats are discoverable.
- No formal WCAG conformance claim is made. Browser smoke inspection is not a substitute for screen-reader, zoom, contrast and mobile-device testing.
