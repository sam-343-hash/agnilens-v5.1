# Changelog

## Unreleased — AgniLens v5.1 engineering and UX audit

- Validate ISO dates, paired ranges, finite numeric parameters, integer/year values and bounded query periods.
- Scope overview and import counts to the selected region; make map thinning operate over the filtered result set.
- Limit simultaneous archive import workers and surface unexpected worker launch/runtime failures.
- Validate JSON/GeoJSON structure and required CSV columns earlier in the import flow; sanitize upload filenames and return structured upload-limit errors.
- Improve first-use onboarding, shared navigation accessibility, busy/error states, import feedback, map status, chart fallbacks, calendar keyboard interaction and export period validation.
- Add regression tests and publish engineering, UX, test-results and manual-QA documentation.
