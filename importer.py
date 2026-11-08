"""NASA FIRMS archive import (CSV/JSON/GeoJSON) and live NRT ingestion. Raw values are preserved."""
import csv, io, json, logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import analytics
import db
import harmonize as H

log = logging.getLogger("agnilens.import")
# Only mappings we are confident about. Anything else is kept verbatim and flagged.
SAT = {"T": "Terra", "TERRA": "Terra", "A": "Aqua", "AQUA": "Aqua", "N": "Suomi NPP",
       "SNPP": "Suomi NPP", "S NPP": "Suomi NPP", "SUOMI NPP": "Suomi NPP", "SUOMI-NPP": "Suomi NPP", "S-NPP": "Suomi NPP",
       "N20": "NOAA-20", "NOAA20": "NOAA-20", "NOAA 20": "NOAA-20", "NOAA-20": "NOAA-20", "J1": "NOAA-20",
       "N21": "NOAA-21", "NOAA21": "NOAA-21", "NOAA 21": "NOAA-21", "NOAA-21": "NOAA-21", "J2": "NOAA-21"}
NRT_SOURCES = {"MODIS_NRT": "MODIS", "VIIRS_SNPP_NRT": "VIIRS", "VIIRS_NOAA20_NRT": "VIIRS", "VIIRS_NOAA21_NRT": "VIIRS"}
INSERT = ("INSERT OR IGNORE INTO satellite_observations(scope,sensor,satellite,product,version,acq_date,acq_time,acq_utc,lat,lon,"
          "frp,brightness,confidence_raw,daynight,origin,source_ref,import_id,flags,platform_raw,raw_record) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
# Links this import to the canonical observation (new or already known), keeping per-source version/confidence/FRP.
LINK = ("INSERT OR IGNORE INTO observation_sources(observation_id,import_id,origin,source_ref,version,confidence_raw,frp,platform_raw,raw_record) "
        "SELECT id,?,?,?,?,?,?,?,? FROM satellite_observations WHERE scope=? AND sensor=? AND satellite=? AND acq_utc=? AND lat=? AND lon=?")


def parse_records(filename, content):
    text = content.decode("utf-8-sig", errors="replace")
    name = (filename or "").lower()
    if name.endswith((".shp", ".zip")):
        raise ValueError("Shapefile import is not supported yet. Export CSV or JSON from FIRMS.")
    if name.endswith((".json", ".geojson")):
        data = json.loads(text)
        if isinstance(data, dict) and "features" in data:
            if not isinstance(data["features"], list):
                raise ValueError("GeoJSON 'features' must be an array.")
            out = []
            for f in data["features"]:
                if not isinstance(f, dict):
                    raise ValueError("Every GeoJSON feature must be an object.")
                props = f.get("properties") or {}
                if not isinstance(props, dict):
                    raise ValueError("GeoJSON feature properties must be an object.")
                p = dict(props)
                geometry = f.get("geometry") or {}
                if not isinstance(geometry, dict):
                    raise ValueError("GeoJSON feature geometry must be an object or null.")
                coords = geometry.get("coordinates") or []
                if geometry.get("type") in (None, "Point") and isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    c = coords
                    p.setdefault("longitude", c[0])
                    p.setdefault("latitude", c[1])
                out.append(p)
            return out
        if isinstance(data, dict):
            data = data.get("data", data.get("records"))
        if not isinstance(data, list):
            raise ValueError("JSON must contain an array of FIRMS records, or a GeoJSON FeatureCollection.")
        if any(not isinstance(row, dict) for row in data):
            raise ValueError("Every JSON record must be an object.")
        return data
    reader = csv.DictReader(io.StringIO(text))
    fields = {str(field or "").strip().lower() for field in (reader.fieldnames or [])}
    required = {"latitude", "longitude", "acq_date", "acq_time"}
    missing = sorted(required - fields)
    if missing:
        raise ValueError("CSV is missing required FIRMS columns: " + ", ".join(missing))
    return list(reader)


def validate_firms_csv(text):
    """Reject error pages/CSV payloads that do not have the FIRMS point fields we consume."""
    reader = csv.DictReader(io.StringIO(text))
    fields = {str(f or "").strip().lower() for f in (reader.fieldnames or [])}
    required = {"latitude", "longitude", "acq_date", "acq_time", "satellite"}
    missing = sorted(required - fields)
    if missing:
        raise ValueError("Unexpected FIRMS response; missing columns: " + ", ".join(missing))
    return reader


def to_observation(r, forced_sensor=None):
    """-> (observation dict, None) or (None, reject reason)."""
    lat, lon = H._f(r.get("latitude")), H._f(r.get("longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, "invalid_coordinates"
    try:
        ts = H._ts(r["acq_date"], r["acq_time"])
    except (KeyError, ValueError, TypeError):
        return None, "invalid_timestamp"
    inst = str(r.get("instrument") or "").upper()
    if "MODIS" in inst:
        sensor = "MODIS"
    elif "VIIRS" in inst or "bright_ti4" in r:
        sensor = "VIIRS"
    elif "bright_t31" in r and "brightness" in r:
        sensor = "MODIS"
    else:
        sensor = forced_sensor
    if sensor not in ("MODIS", "VIIRS"):
        return None, "unknown_sensor"
    raw_sat = str(r.get("satellite") or "").strip()
    sat, flags = SAT.get(raw_sat.upper().replace("_", " ")), []
    if sat is None:
        sat = raw_sat or "unknown"
        flags.append("unrecognised_satellite")
    frp = H._f(r.get("frp"))
    if frp is not None and frp < 0:
        return None, "negative_frp"
    if frp is None:
        flags.append("missing_frp")
    bright = H._f(r.get("brightness") if sensor == "MODIS" else r.get("bright_ti4"))
    return {"sensor": sensor, "satellite": sat, "platform_raw": raw_sat, "raw_record": dict(r), "product": inst or sensor, "version": str(r.get("version") or ""),
            "acq_date": ts.strftime("%Y-%m-%d"), "acq_time": str(r["acq_time"]).strip().zfill(4),
            "acq_utc": ts.strftime("%Y-%m-%dT%H:%M:00Z"), "lat": lat, "lon": lon, "frp": frp, "brightness": bright,
            "confidence_raw": str(r.get("confidence", "")).strip(), "daynight": str(r.get("daynight") or ""),
            "flags": ",".join(flags)}, None


def resolve_extent(conn, extent, custom=None):
    """Declared geographical extent -> ([w,s,e,n], label). Never inferred from the data."""
    if extent == "custom":
        b = db.validate_bbox(*(custom or [None] * 4))
        return b, f"Custom box {b[0]},{b[1]} to {b[2]},{b[3]}"
    r = conn.execute("SELECT * FROM regions WHERE id=?", (extent,)).fetchone()
    if not r:
        raise ValueError("Choose the geographical extent of the file: Punjab, Haryana, Punjab + Haryana, India or a custom box.")
    return [r["west"], r["south"], r["east"], r["north"]], f"{r['name']} (approximate box)"


def create_import(conn, filename, origin, source_name=None, sensors="", bbox=None, extent_label=None):
    cur = conn.execute("INSERT INTO data_imports(filename,origin,source_name,sensors,status,bbox,extent_label,started_at) VALUES(?,?,?,?,?,?,?,?)",
                       (filename, origin, source_name, sensors, "running", json.dumps(bbox) if bbox else None, extent_label, db.now()))
    conn.commit()
    return cur.lastrowid


def import_records(conn, iid, records, origin, forced_sensor=None, source_ref="", chunk=2000):
    """Canonical observations are unique per (scope, sensor, satellite, UTC time, lat, lon) at full source precision.
    An observation already known from another import is not counted again, but this import is still linked to it."""
    scope = "demo" if origin == "demo" else "nasa"
    rej, batch, sensors = Counter(), [], set()
    st = {"imp": 0, "dup": 0, "done": 0, "dmin": None, "dmax": None}

    def flush():
        if batch:
            before = conn.total_changes
            conn.executemany(INSERT, [(scope, o["sensor"], o["satellite"], o["product"], o["version"], o["acq_date"], o["acq_time"],
                                       o["acq_utc"], o["lat"], o["lon"], o["frp"], o["brightness"], o["confidence_raw"], o["daynight"],
                                       origin, source_ref, iid, o["flags"], o["platform_raw"], json.dumps(o["raw_record"], default=str, ensure_ascii=False)) for o in batch])
            n = conn.total_changes - before
            conn.executemany(LINK, [(iid, origin, source_ref, o["version"], o["confidence_raw"], o["frp"], o["platform_raw"],
                                     json.dumps(o["raw_record"], default=str, ensure_ascii=False), scope, o["sensor"],
                                     o["satellite"], o["acq_utc"], o["lat"], o["lon"]) for o in batch])
            st["imp"] += n
            st["dup"] += len(batch) - n
            batch.clear()
        conn.execute("UPDATE data_imports SET rows_processed=?,rows_imported=?,rows_duplicate=?,rows_rejected=? WHERE id=?",
                     (st["done"], st["imp"], st["dup"], sum(rej.values()), iid))
        conn.commit()

    for r in records:
        st["done"] += 1
        o, why = to_observation(r, forced_sensor)
        if o is None:
            rej[why] += 1
        else:
            sensors.add(o["sensor"])
            st["dmin"] = min(st["dmin"] or o["acq_date"], o["acq_date"])
            st["dmax"] = max(st["dmax"] or o["acq_date"], o["acq_date"])
            batch.append(o)
        if len(batch) >= chunk:
            flush()
    flush()
    return {"sensors": sensors, "rejected": dict(rej), "imported": st["imp"], "duplicates": st["dup"],
            "date_min": st["dmin"], "date_max": st["dmax"]}


def import_file(filename, content, origin="nasa_archive", sensor=None, cov_start=None, cov_end=None, import_id=None,
                bbox=None, extent_label=None):
    """Synchronous import (the API runs it in a background thread). bbox is the DECLARED geographical extent;
    without it the file provides no regional coverage. Returns the import id."""
    conn = db.connect()
    iid = import_id or create_import(conn, filename, origin)
    try:
        recs = parse_records(filename, content)
        conn.execute("UPDATE data_imports SET rows_total=? WHERE id=?", (len(recs), iid))
        conn.commit()
        s = import_records(conn, iid, recs, origin, sensor, source_ref=filename)
        assumed = 0
        if not (cov_start and cov_end):
            cov_start, cov_end, assumed = s["date_min"], s["date_max"], 1
        sensors = {sensor} if sensor else s["sensors"]
        conn.execute("UPDATE data_imports SET status='done',sensors=?,coverage_start=?,coverage_end=?,coverage_assumed=?,"
                     "reject_summary=?,bbox=?,extent_label=?,finished_at=? WHERE id=?",
                     (",".join(sorted(sensors)), cov_start, cov_end, assumed, json.dumps(s["rejected"]),
                      json.dumps(bbox) if bbox else None, extent_label, db.now(), iid))
        conn.commit()
        analytics.rebuild_activity(conn, "demo" if origin == "demo" else "nasa")
    except Exception as ex:
        log.exception("import failed")
        conn.execute("UPDATE data_imports SET status='error',error=?,finished_at=? WHERE id=?", (str(ex)[:300], db.now(), iid))
        conn.commit()
    finally:
        conn.close()
    return iid


def nrt_coverage(days, now=None):
    """Only full UTC days strictly inside the requested window count as covered."""
    now = now or datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)
    start = (start_dt + timedelta(days=1)).date() if (start_dt.hour or start_dt.minute) else start_dt.date()
    end = (now - timedelta(days=1)).date()
    return (start.isoformat(), end.isoformat()) if start <= end else (None, None)


def _fetch_firms(key, source, bbox, days):
    import requests
    w, s, e, n = bbox
    r = requests.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{w},{s},{e},{n}/{days}", timeout=40)
    r.raise_for_status()
    return r.text


def ingest_nrt(key, days=1, bbox=db.STUDY_BBOX, fetch=None):
    """One import row per source, so a failed source is never mistaken for zero detections."""
    fetch, results = fetch or _fetch_firms, []
    cs, ce = nrt_coverage(days)
    for src, sensor in NRT_SOURCES.items():
        conn = db.connect()
        iid = create_import(conn, f"{src} (last {days} d)", "nasa_nrt", src, sensor, list(bbox), "Punjab + Haryana study area (approximate box)")
        try:
            text = fetch(key, src, bbox, days)
            reader = validate_firms_csv(text)
            s = import_records(conn, iid, list(reader), "nasa_nrt", sensor, source_ref=src)
            conn.execute("UPDATE data_imports SET status='done',coverage_start=?,coverage_end=?,reject_summary=?,finished_at=?,"
                         "rows_total=rows_processed WHERE id=?", (cs, ce, json.dumps(s["rejected"]), db.now(), iid))
            conn.commit()
            results.append({"source": src, "status": "ok", "rows": s["imported"] + s["duplicates"], "new": s["imported"],
                            "import_id": iid, "retrieved_at": db.now()})
        except Exception as ex:
            msg = str(ex).replace(key, "***")[:200]
            log.warning("NRT source %s failed: %s", src, msg)
            conn.execute("UPDATE data_imports SET status='error',error=?,finished_at=? WHERE id=?", (msg, db.now(), iid))
            conn.commit()
            results.append({"source": src, "status": "error", "error": msg, "import_id": iid, "retrieved_at": db.now()})
        finally:
            analytics.rebuild_activity(conn, "nasa")
            conn.close()
    return results
