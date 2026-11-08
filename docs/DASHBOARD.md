# Monitoring dashboard

The Overview is a live view over records already stored in the selected scope (nasa or demo) and selected approximate region. Its summary cards and charts do not generate data. The map uses the same dates and sensor selection as the timeline. Region and scope are shared shell filters; changing either updates the view across pages.

## Activity API

GET /api/activity?scope=nasa&region=in-pb-hr&range=30d&sensor=MODIS,VIIRS

Supported ranges are 24h, 7d, 30d, 90d, and custom. Custom requests require ISO start and end calendar dates and are limited to 365 days. The 24-hour view is hourly in UTC; other ranges are daily in UTC. Optional sensor accepts MODIS, VIIRS or both.

Each series bucket returns MODIS and VIIRS observation counts and high-confidence subsets. Missing buckets are null unless the selected sensor has a confirmed declared coverage interval for that day, in which case an empty bucket is zero. Assumed coverage alone does not turn a missing observation into zero. This prevents the chart from filling uncovered history with invented zeros.

The displayed “high confidence” subtotal is a transparent display grouping: MODIS raw confidence of 80 or above, or VIIRS raw confidence h/high. It is not a calibrated probability, and the sensor confidence scales are not directly comparable. Missing and other raw confidence values are not classified as high.

The response includes period totals, the number of seeded approximate region boxes with observations in the selected period, and the most recent observation timestamp in the selected region. Approximate boxes overlap, so the active-region card is a count of boxes containing data, not a count of non-overlapping administrative regions.

The map continues to use GET /api/map/observations. It supports the existing inclusive start and end filters plus optional timezone-qualified ISO since, used by the rolling 24-hour dashboard view. Limit caps returned points; clustering and heat display are visual treatments and do not alter stored observations or summary counts.

## UI behavior

- The shared sidebar preserves all established routes, including Harmonization and Experimental; it collapses on desktop and becomes a modal drawer at narrow widths.
- Global scope and region controls stay visible in the top bar. Demo scope is clearly marked synthetic.
- Chart legend items toggle individual series. Sensor checkboxes also scope the KPIs and map points. Date-range changes update the chart and map together.
- Reset returns to 30 days, enables both sensors and points, and disables heat display.
- A chart or map CDN failure shows a visible fallback. OpenStreetMap tile loading still requires network access.
- The map is limited to 5,000 returned observations and clusters dense point groups. The current selectable regions are approximate Punjab, Haryana, Punjab + Haryana and India boxes; this is not worldwide FIRMS coverage.
