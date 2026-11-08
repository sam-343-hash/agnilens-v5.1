# AgniLens data dictionary

## Core tables

| Table | Purpose | Important fields |
|---|---|---|
| `satellite_observations` | Canonical raw detections, one per exact identity and scope | `scope` (`nasa` / `demo`), `sensor`, normalized `satellite`, `platform_raw`, UTC acquisition time, original coordinates, FRP, brightness, confidence, product/version, origin, flags and full `raw_record` JSON |
| `observation_sources` | One row for each import/query that reported a canonical observation | observation/import IDs, origin, source reference, source-specific version, confidence, FRP, raw platform label and source `raw_record` JSON |
| `data_imports` | Import/query status, accounting, and declared extent/coverage | filename/source, status, rows received/processed/accepted/duplicate/rejected, rejection summary, dates, coverage quality, approximate bbox/label, timestamps and error |
| `processing_runs` | Parameters and summary for a harmonization or analysis run | scope, region, period, serialized parameters and summary, run timestamps |
| `harmonization_matches` | Candidate MODIS–VIIRS pair edges for a run | MODIS ID, VIIRS ID, distance, time difference and group ID |
| `correspondence_groups` | Connected components of candidate pair edges | group ID, member counts per sensor and first observation date |
| `daily_activity` | Per-region/per-day/per-sensor detection aggregates | counts, FRP mean/max, candidate-pair/group counts, scope and region |
| `monthly_activity` | Per-region/per-month/per-sensor detection aggregates | counts and FRP mean/max, scope and region |
| `regions` | Named approximate bounding boxes | region ID/name/country, bounds, explanatory note |

## Units and meanings

- Coordinates are decimal degrees in WGS84-like FIRMS point form; raw coordinates are not snapped or rounded in canonical identity.
- Acquisition time is UTC. Source `acq_time` is preserved in the observation alongside normalized `acq_utc`.
- FRP is in the source product's reported units and is summarized separately for MODIS and VIIRS; cross-sensor FRP is never combined.
- MODIS confidence and VIIRS categorical confidence are different scales. A coarse display category does not make them equivalent.
- `active`, `confirmed_zero`, `assumed_coverage`, and `no_data` describe data/coverage states, not fire behavior.
- A candidate pair/group is a spatiotemporal relation under configured cutoffs, not a verified physical fire.
- `platform_raw` and `raw_record` are null for records imported before schema migrations v3/v4 when the original source record cannot be recovered.

## Import counters

`rows_total` is records parsed from the file; `rows_processed` is records visited; `rows_imported` is newly inserted canonical detections; `rows_duplicate` are valid records linked to an existing canonical detection; `rows_rejected` are invalid records with reason counts in `reject_summary`. The import bbox is the declared/requested extent, not a geometry inferred from detections.
