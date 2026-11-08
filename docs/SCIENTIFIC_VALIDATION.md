# Scientific validation record

## Scope and current status

**Real-data experiment status: pending.** The supplied project did not include a NASA FIRMS archive file or a MAP_KEY, and no genuine Punjab/Haryana MODIS–VIIRS month was available in the working directory. Therefore this document reports no real-data counts, correspondence rates, spatial overlap, temporal agreement, or anomaly accuracy. Synthetic unit-test fixtures verify software behavior only; they do not validate scientific accuracy.

## Reproducible Punjab + Haryana experiment

1. Request the same manageable calendar month and approximate Punjab + Haryana bounds from NASA FIRMS for MODIS C6.1 and VIIRS S-NPP, NOAA-20, and NOAA-21 (375 m). The official FIRMS Area API documents the supported area CSV request and source names at the [Area API reference](https://firms.modaps.eosdis.nasa.gov/api/area/). Historical archive exports should be obtained through the FIRMS download workflow; this project does not assume a public historical endpoint.
2. Keep original downloads unchanged. Record the product/source, request date, bounds and requested dates. The utility records each input's SHA-256 and file path in its JSON output.
3. Run from this directory:

   ```sh
   python validate_archive_pair.py /path/to/modis.csv /path/to/viirs.csv \
     --bbox 73.8,27.6,77.6,32.6 --out work/punjab-haryana-month.json
   ```

   Defaults compare 500 m / 30 min, 1,000 m / 120 min, and 2,000 m / 240 min. Supply `--thresholds DIST:MIN,...` to change them. The 1 km / 120 minute configuration is a reference setting, not a validated optimum.
4. Inspect per-file records received/accepted/duplicate/rejected, rejection reasons, date range and canonical platform counts. Compare these totals with the original file row counts. The report includes daily MODIS and VIIRS detection totals and, per configuration, candidate pairs, connected groups, matched observation fractions, and median spatial and temporal separations.
5. Import the same files in **Data**, declare the approximate extent and explicit file coverage dates, then verify the application import counters and calendar daily counts against the report. Run the same threshold configurations in **Harmonization** and compare run summaries.

The matching report measures algorithmic consistency and parameter sensitivity. It does not establish that pairs are the same physical fires. Scientific accuracy would additionally require independent reference observations or expert-reviewed correspondences and a defined sampling/measurement protocol.

## Evidence categories

| Category | Evidence available now | What it does not show |
|---|---|---|
| Software correctness | Automated unit and API tests with controlled fixtures; migration checks | Real-data accuracy or sensor agreement |
| Data integrity | Exact-identity duplicate handling, raw record/source provenance, alias normalization and declared extent/coverage checks | NASA authentication of user-supplied archive files |
| Algorithmic consistency | Deterministic distance/time matching; reproducible threshold-sensitivity utility | Calibrated match probabilities or optimal thresholds |
| Scientific validation | Not performed; no real archive pair or independent truth data was supplied | Precision, recall, bias, anomaly performance or physical-fire identity |

## Required follow-up before scientific claims

- Execute the experiment with a real, same-period archive export from each sensor/platform.
- Verify file/product metadata and accepted/rejected counts against the original records.
- Review candidate spatial and temporal distributions, including unmatched observations, under several cutoff settings.
- Establish independent ground truth and a sampling protocol before estimating precision/recall or selecting thresholds.
- Assess partial-period coverage, platform availability and thermal detection differences before comparing counts or anomalies.

No statements about validated thresholds, verified fires, or anomaly prediction should be made from the present software test results.
