# AgniLens scientific methodology

AgniLens reports **satellite detections** and **candidate cross-sensor correspondences**. It does not count individual fires, verify that two detections are the same fire, or predict wildfires.

## 1. Normalisation
Each FIRMS record becomes one observation with: sensor (MODIS or VIIRS), normalized satellite (Terra, Aqua, Suomi NPP, NOAA-20, NOAA-21; unknown codes are kept verbatim and flagged), raw source platform label, UTC timestamp built from `acq_date` + `acq_time` (HHMM), latitude, longitude, FRP, brightness temperature (MODIS `brightness`, VIIRS `bright_ti4`), raw confidence, day/night, product/version, origin and import batch. The source platform label is retained both on the canonical observation and in per-import provenance. Records are rejected (and counted by reason) for invalid coordinates, invalid timestamps, unknown sensor or negative FRP. Missing FRP is flagged, not dropped.

**Platform normalization.** Aliases such as `SNPP` / `S-NPP`, `NOAA20` / `N20` / `J1`, and `NOAA21` / `N21` / `J2` normalize to canonical platform identities. The original value remains available as `platform_raw`. This makes alias variants comparable while preserving what the source file contained.

**Identity, duplicates and provenance.** A *canonical observation* is identified by (scope, sensor, satellite, UTC time, latitude, longitude) at full source precision; coordinates are never rounded (in the matching engine or the database). `scope` is `nasa` or `demo`, so synthetic and NASA observations can never collide. Only exact repeats within a scope are treated as the same observation. Distinct nearby detections are never merged.
If the same detection arrives from several imports (for example a live NRT retrieval and a later archive export), it is stored once and counted once, and **every** reporting import is kept in `observation_sources` together with that source's own version, raw confidence and FRP. Which imports contributed an observation can always be retrieved (`GET /api/observations/<id>/sources`).

## 2. Spatial comparison
Distance uses the haversine formula, with R = 6371 km:

d = 2R · asin( sqrt( sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2) ) )

For speed, MODIS points are indexed in 0.01° grid cells (about 1.1 km). For a VIIRS point at latitude φ and maximum distance D, the search covers rᵢ = ceil(D / (111000 · 0.01)) cells in latitude and rⱼ = ceil(D / (111000 · 0.01 · cos φ)) cells in longitude.

## 3. Temporal comparison
Δt = |t_VIIRS − t_MODIS| in minutes, both UTC.

## 4. Candidate correspondence and groups
Candidate pairs P = { (m, v) : d(m, v) ≤ D and Δt ≤ T }. This is many-to-many: one MODIS point can pair with several VIIRS points and the reverse. Each pair also reports its distance and time difference as fractions of the configured cutoffs. Those fractions express proximity to the run's limits; they are not calibrated confidence or probability. A correspondence group is a connected component of the bipartite graph formed by P (union-find). Unmatched observations stay as `modis_only` or `viirs_only`.

```
index MODIS points by grid cell
for each VIIRS point v:
    for each cell within (r_i, r_j) of v's cell:
        for each MODIS point m in the cell:
            if haversine(v, m) <= D and |t_v - t_m| <= T: record pair (m, v, d, dt)
union MODIS and VIIRS ids of every pair
group id = component label; observations outside any pair are "only"
```
**Complexity.** Roughly O(N_V · k), where k is the number of MODIS points in the neighbouring cells; worst case O(N_M · N_V) in very dense clusters. Union-find adds near-linear time. The API refuses runs above 30,000 observations.

## 5. Threshold rationale (defaults are not validated)
- **D = 1000 m:** about the nominal MODIS pixel size (1 km, which grows away from nadir). VIIRS pixels are 375 m.
- **T = 120 min:** Aqua, Suomi NPP, NOAA-20 and NOAA-21 pass at roughly the same local afternoon time, while Terra passes roughly three hours earlier. Terra–VIIRS pairs therefore fall outside the default window. Raise T (for example to 240) to include them.
- Both are adjustable in the UI. No accuracy has been measured.

## 6. What is not merged
FRP, raw confidence and counts are kept per sensor. MODIS confidence is 0–100 and VIIRS is low/nominal/high; a coarse low/nominal/high label is stored for display only and is not treated as equivalent. Counts are affected by pixel size, overpass times and the number of platforms.

## 7. Geographical coverage, coverage quality and the historical calendar
**Declared extent.** Every archive import must declare the geographical extent of the file (Punjab, Haryana, Punjab + Haryana, India, or a validated custom box). It is saved in `data_imports.bbox`. Coverage is associated only with regions **fully contained** in that declared extent. Extent is never inferred from where detections appear, and an import without a declared extent provides no regional coverage at all. Regions themselves are *approximate bounding boxes*, not administrative boundaries.

**Coverage dates and quality.** Dates come from the user ("confirmed") or, if left blank, from the first and last detection date in the file ("assumed"). Live NRT coverage counts only full UTC days inside the requested window and only for sources that succeeded.

**Day states per region and sensor**
| State | Meaning |
|---|---|
| `active` | detections exist (always real data) |
| `confirmed_zero` | declared extent and dates cover the day; no detections |
| `assumed_coverage` | only an inferred date range covers the day; **zero cannot be established** |
| `no_data` | no coverage information |

Confirmed coverage wins when both kinds cover a day. Assumed days have no intensity value and are drawn differently in the calendar; the API, calendar warnings and exports state how many days rely on assumed coverage.

Calendar intensity: for the chosen metric (VIIRS count, MODIS count, or their sum when both are known), 0 = confirmed zero, and levels 1–4 are set by the median, 75th and 90th percentile of non-zero days in that year.

## 8. Anomaly detection
For a month (or a day with a ±7-day window) with observed count x, the baseline is the same calendar month in **other years** with at least 80% **confirmed** coverage. The 80% completeness cutoff and minimum of 3 comparable years are configurable heuristics, not universal scientific thresholds. Monthly counts are raw detections; they are not extrapolated to compensate for missing days, so a barely qualifying partial month can remain biased. Assumed coverage is never used, neither for the observed value nor for the baseline; excluded months are counted and reported. At least 3 comparable years are required; otherwise the result is "insufficient baseline" (or "assumed only") and no score is produced.

- Standard: z = (x − mean) / sd
- Robust (used to flag): z_r = (x − median) / max(1.4826 · MAD, sqrt(median)). The square-root term is a Poisson noise floor for count data. A period is flagged when |z_r| ≥ 3.5 (the 3.5 cutoff is the Iglewicz–Hoaglin convention for the MAD-based score).
- **Constellation check (platform identities, not counts).** For each month the set of contributing satellites is built from the stored observations. The observed set A is compared with the most common baseline set B using the Jaccard similarity J = |A ∩ B| / |A ∪ B|. A caveat names the added and missing platforms whenever A ≠ B, even if both sets have the same size, and a second caveat is added when fewer than half of the baseline months share one platform set. Per-sensor and per-platform counts are kept for every month. Daily scores do not check platforms.

## 9. Limitations
- Candidate matches are not proof of the same fire; thresholds are untuned.
- Sensor constellations changed over time, so long-term count trends mix real change with coverage change.
- Regions are bounding boxes that include parts of neighbouring areas. Admin boundaries are not used yet.
- The archive importer trusts the file; it cannot verify NASA provenance. Shapefiles are not supported.
- Coverage is tracked per sensor and successful import/query, not as a day-by-day platform observation-quality mask. A successful platform query with zero records is evidence that the source responded for the requested range, not proof of pixel-level clear-sky coverage. The platform-set anomaly check only sees platforms that produced detections.
- Legacy imports made before extents were required have no declared extent and give no regional coverage until one is declared (`POST /api/imports/<id>/extent`).
- A detection reported by several sources is counted once; the first source's values are shown on the observation, other sources' values are in the provenance table.
- **Software tests check the code against synthetic cases with known answers. They are not scientific validation.** No accuracy, precision or recall against ground truth has been measured.
