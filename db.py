"""SQLite persistence (versioned migrations via PRAGMA user_version). Schema is PostGIS-portable."""
import math
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("AGNILENS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agnilens.db"))

MIGRATIONS = ["""
CREATE TABLE regions(id TEXT PRIMARY KEY,name TEXT,country TEXT,west REAL,south REAL,east REAL,north REAL,note TEXT);
CREATE TABLE data_imports(id INTEGER PRIMARY KEY AUTOINCREMENT,filename TEXT,origin TEXT NOT NULL,source_name TEXT,
 sensors TEXT,status TEXT,rows_total INTEGER DEFAULT 0,rows_processed INTEGER DEFAULT 0,rows_imported INTEGER DEFAULT 0,
 rows_duplicate INTEGER DEFAULT 0,rows_rejected INTEGER DEFAULT 0,reject_summary TEXT,coverage_start TEXT,coverage_end TEXT,
 coverage_assumed INTEGER DEFAULT 0,bbox TEXT,started_at TEXT,finished_at TEXT,error TEXT);
CREATE TABLE satellite_observations(id INTEGER PRIMARY KEY AUTOINCREMENT,sensor TEXT NOT NULL,satellite TEXT,product TEXT,
 version TEXT,acq_date TEXT NOT NULL,acq_time TEXT,acq_utc TEXT NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL,frp REAL,
 brightness REAL,confidence_raw TEXT,daynight TEXT,origin TEXT NOT NULL,source_ref TEXT,
 import_id INTEGER REFERENCES data_imports(id),flags TEXT,UNIQUE(sensor,satellite,acq_utc,lat,lon));
CREATE INDEX idx_obs_date ON satellite_observations(acq_date);
CREATE INDEX idx_obs_sensor_date ON satellite_observations(sensor,acq_date);
CREATE INDEX idx_obs_geo ON satellite_observations(lat,lon);
CREATE INDEX idx_obs_import ON satellite_observations(import_id);
CREATE TABLE processing_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,scope TEXT,region_id TEXT,start_date TEXT,
 end_date TEXT,params TEXT,summary TEXT,started_at TEXT,finished_at TEXT);
CREATE TABLE harmonization_matches(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id INTEGER REFERENCES processing_runs(id),
 modis_id INTEGER,viirs_id INTEGER,distance_m REAL,dt_min REAL,group_id TEXT);
CREATE INDEX idx_match_run ON harmonization_matches(run_id);
CREATE TABLE correspondence_groups(run_id INTEGER REFERENCES processing_runs(id),group_id TEXT,n_modis INTEGER,
 n_viirs INTEGER,first_date TEXT,PRIMARY KEY(run_id,group_id));
CREATE TABLE daily_activity(scope TEXT,region_id TEXT,date TEXT,modis_count INTEGER,viirs_count INTEGER,modis_frp_mean REAL,
 modis_frp_max REAL,viirs_frp_mean REAL,viirs_frp_max REAL,candidate_pairs INTEGER,candidate_groups INTEGER,
 PRIMARY KEY(scope,region_id,date));
CREATE TABLE monthly_activity(scope TEXT,region_id TEXT,month TEXT,modis_count INTEGER,viirs_count INTEGER,
 modis_frp_mean REAL,modis_frp_max REAL,viirs_frp_mean REAL,viirs_frp_max REAL,PRIMARY KEY(scope,region_id,month));
"""]

# v2: canonical observation identity is scoped (demo vs nasa); every import that reported an observation is kept in
# observation_sources; imports gain a human-readable extent label. Rebuilds the table so existing databases keep their data.
MIGRATIONS.append("""
BEGIN;
ALTER TABLE data_imports ADD COLUMN extent_label TEXT;
CREATE TABLE satellite_observations_v2(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,sensor TEXT NOT NULL,
 satellite TEXT,product TEXT,version TEXT,acq_date TEXT NOT NULL,acq_time TEXT,acq_utc TEXT NOT NULL,lat REAL NOT NULL,
 lon REAL NOT NULL,frp REAL,brightness REAL,confidence_raw TEXT,daynight TEXT,origin TEXT NOT NULL,source_ref TEXT,
 import_id INTEGER REFERENCES data_imports(id),flags TEXT,UNIQUE(scope,sensor,satellite,acq_utc,lat,lon));
INSERT INTO satellite_observations_v2(id,scope,sensor,satellite,product,version,acq_date,acq_time,acq_utc,lat,lon,frp,
 brightness,confidence_raw,daynight,origin,source_ref,import_id,flags)
 SELECT id,CASE WHEN origin='demo' THEN 'demo' ELSE 'nasa' END,sensor,satellite,product,version,acq_date,acq_time,acq_utc,
 lat,lon,frp,brightness,confidence_raw,daynight,origin,source_ref,import_id,flags FROM satellite_observations;
DROP TABLE satellite_observations;
ALTER TABLE satellite_observations_v2 RENAME TO satellite_observations;
CREATE INDEX idx_obs_date ON satellite_observations(acq_date);
CREATE INDEX idx_obs_sensor_date ON satellite_observations(sensor,acq_date);
CREATE INDEX idx_obs_geo ON satellite_observations(lat,lon);
CREATE INDEX idx_obs_import ON satellite_observations(import_id);
CREATE INDEX idx_obs_scope_date ON satellite_observations(scope,acq_date);
CREATE TABLE observation_sources(observation_id INTEGER NOT NULL REFERENCES satellite_observations(id) ON DELETE CASCADE,
 import_id INTEGER NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,origin TEXT,source_ref TEXT,version TEXT,
 confidence_raw TEXT,frp REAL,PRIMARY KEY(observation_id,import_id));
CREATE INDEX idx_src_import ON observation_sources(import_id);
INSERT INTO observation_sources(observation_id,import_id,origin,source_ref,version,confidence_raw,frp)
 SELECT id,import_id,origin,source_ref,version,confidence_raw,frp FROM satellite_observations WHERE import_id IS NOT NULL;
PRAGMA user_version=2;
COMMIT;
""")

# v3: keep source platform labels while querying a normalized platform identity.
MIGRATIONS.append("""
BEGIN;
ALTER TABLE satellite_observations ADD COLUMN platform_raw TEXT;
ALTER TABLE observation_sources ADD COLUMN platform_raw TEXT;
PRAGMA user_version=3;
COMMIT;
""")

# v4: retain the complete input object for each canonical record and each source link.
MIGRATIONS.append("""
BEGIN;
ALTER TABLE satellite_observations ADD COLUMN raw_record TEXT;
ALTER TABLE observation_sources ADD COLUMN raw_record TEXT;
PRAGMA user_version=4;
COMMIT;
""")

NOTE = "Approximate bounding box, not an administrative boundary; it also includes parts of neighbouring areas."
REGIONS = [
    ("in-pb-hr", "Punjab + Haryana (study area)", "India", 73.8, 27.6, 77.6, 32.6, NOTE),
    ("in-punjab", "Punjab", "India", 73.88, 29.53, 76.94, 32.51, NOTE),
    ("in-haryana", "Haryana", "India", 74.46, 27.65, 77.60, 30.93, NOTE),
    ("in-all", "India (approximate box)", "India", 68.0, 6.5, 97.5, 37.1, NOTE),
]
STUDY_BBOX = (73.8, 27.6, 77.6, 32.6)  # west, south, east, north (= in-pb-hr)


def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    c = connect()
    v = c.execute("PRAGMA user_version").fetchone()[0]
    for i in range(v, len(MIGRATIONS)):
        c.executescript(MIGRATIONS[i])
        c.execute(f"PRAGMA user_version={i + 1}")
    if not c.execute("SELECT 1 FROM regions LIMIT 1").fetchone():
        c.executemany("INSERT INTO regions VALUES(?,?,?,?,?,?,?,?)", REGIONS)
    c.commit()
    c.close()


def scope_clause(scope):
    return "scope='demo'" if scope == "demo" else "scope='nasa'"


def validate_bbox(w, s, e, n):
    try:
        w, s, e, n = [float(x) for x in (w, s, e, n)]
    except (TypeError, ValueError):
        raise ValueError("Bounding box values must be numbers (west, south, east, north).")
    if not all(math.isfinite(x) for x in (w, s, e, n)) or not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Bounding box must satisfy -180 <= west < east <= 180 and -90 <= south < north <= 90.")
    return [w, s, e, n]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
