# AgniLens · Unified Satellite Fire Intelligence
NASA Space Apps Challenge 2026: *Harmonization of MODIS and VIIRS Hot Spots*.

## Run
```
python3 -m venv .venv
. .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
export FIRMS_MAP_KEY=your_key        # optional; required only for live NASA retrieval
python app.py                        # http://127.0.0.1:5001
python -m unittest discover -s tests
```
For persistent local configuration, copy `.env.example` to `.env` and add your FIRMS key there. `.env` is git-ignored and loaded on startup; a value already set in the shell takes precedence. Windows PowerShell can instead set `$env:FIRMS_MAP_KEY="your_key"`. The local development server uses port **5001** by default (`PORT` can change it). Debug mode is off unless explicitly enabled for local development.

The repo is a Flask app with static HTML/JavaScript and SQLite; there is no separate frontend build step. Uploads are limited to 50 MiB and accepted formats are CSV, JSON and GeoJSON.

### If your virtual environment is corrupted

If `pip` reports missing internal modules or Flask/Werkzeug reports missing package files, do not reuse that environment. Deactivate it and create a new one under a different name:

```sh
deactivate  # if an environment is active
python3 -m venv .venv-clean
.venv-clean/bin/python -m pip install -r requirements.txt
.venv-clean/bin/python app.py
```

## First use
1. Open **Data**. Either click *Retrieve live NRT data* (needs the key), import a FIRMS archive CSV/JSON, or load the clearly labelled **synthetic demo** and switch the scope selector to *Demo*.
2. Open **Harmonization**, **Calendar**, **Anomalies**, **Map**, **MODIS vs VIIRS**, **Regions** and **Reports**.
3. For real history, request MODIS and VIIRS archive exports for Punjab and Haryana from the [NASA FIRMS download portal](https://firms.modaps.eosdis.nasa.gov/download/) (archive access can require registration and data delivery). Import each returned file. On import, declare its geographical extent (Punjab, Haryana, Punjab + Haryana, India or a custom box; these are approximate boxes) and the actual period the source file covers. If you omit coverage dates, the file’s first and last detection dates are only *assumed* coverage; quiet days show as “assumed coverage,” not confirmed zero, and assumed dates are excluded from anomaly baselines.

### Reproducible real-data import

1. From FIRMS, request one bounded calendar month for each product: MODIS C6.1, VIIRS Suomi-NPP 375 m, VIIRS NOAA-20 375 m and VIIRS NOAA-21 375 m, using the same Punjab + Haryana study extent.
2. Keep the downloaded files unchanged and record the request/product, retrieval date, requested bounds and coverage dates.
3. Upload each file separately on **Data**, choose its sensor, select `Punjab + Haryana`, and enter the request’s coverage start and end (do not infer dates from detections).
4. Wait for the import status to finish; inspect accepted, duplicate and rejected counts, date range and declared extent.
5. Select the same region and period in **Harmonization** and compare more than one spatial/temporal cutoff. Record the run IDs and parameters with any exported report.

FIRMS file imports retain source and platform labels but cannot independently prove that a user-supplied file was delivered by NASA. Historical archive access is not implemented through a guessed public API endpoint.

## Coverage and provenance (V5.1)
- Calendar day states: **active**, **confirmed zero**, **assumed coverage**, **no data**. Coverage applies only to regions fully inside the extent you declared; it is never inferred from where detections appear.
- A detection seen by several imports (for example NRT and an archive export) is counted once, and all its sources stay retrievable.
- Synthetic demo data lives in its own scope and can never collide with NASA data.
- **Upgrading an existing database:** just start the app; the schema upgrades automatically and keeps your data. Imports made before V5.1 have no declared extent and give no regional coverage until you declare one, for example:
  `curl -X POST -H "Content-Type: application/json" -d '{"extent":"in-pb-hr"}' http://127.0.0.1:5001/api/imports/1/extent`
  (extent values: `in-punjab`, `in-haryana`, `in-pb-hr`, `in-all`, or `custom` with `west`, `south`, `east`, `north`).

## Docs
`docs/METHODOLOGY.md` (equations, assumptions and limits), `docs/ARCHITECTURE.md`, `docs/DATA_DICTIONARY.md`, `docs/SCIENTIFIC_VALIDATION.md`, `BUILD_REPORT.md`.
The old Stubble Watch heuristic is kept as **Experimental** (`/experimental`) and is unvalidated.
