"""AgniLens JSON API. FIRMS_MAP_KEY stays server-side; never returned to the browser."""
import html, json, logging, math, os, threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Response, jsonify, request

import analytics, db, demo_data, importer
from werkzeug.utils import secure_filename

log = logging.getLogger("agnilens.api")
bp = Blueprint("agnilens", __name__)
KEY = lambda: os.getenv("FIRMS_MAP_KEY", "")
_IMPORT_SLOTS = threading.BoundedSemaphore(2)


def _background_import(*args):
    iid = args[6]
    try:
        importer.import_file(*args)
    except Exception as ex:
        log.exception("background import worker failed")
        c = db.connect()
        try:
            c.execute("UPDATE data_imports SET status='error',error=?,finished_at=? WHERE id=?",
                      (str(ex)[:300], db.now(), iid))
            c.commit()
        finally:
            c.close()
    finally:
        _IMPORT_SLOTS.release()


def _scope_region():
    scope = request.args.get("scope", "nasa")
    if scope not in ("nasa", "demo"):
        raise ValueError("scope must be 'nasa' or 'demo'")
    return scope, request.args.get("region", "in-pb-hr")


def _d(name, default=None):
    v = request.args.get(name, default)
    if v:
        try:
            if date.fromisoformat(v).isoformat() != v:
                raise ValueError
        except ValueError as ex:
            raise ValueError(f"{name} must be a real date in YYYY-MM-DD format") from ex
    return v


def _num(name, default, lo, hi):
    try:
        value = float(request.args.get(name, default))
        if not math.isfinite(value):
            raise ValueError
        return min(max(value, lo), hi)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")


def _date_range(require_both=False, max_years=None):
    start, end = _d("start"), _d("end")
    if require_both and not (start and end):
        raise ValueError("start and end dates are required (YYYY-MM-DD)")
    if bool(start) != bool(end):
        raise ValueError("Provide both start and end dates, or neither.")
    if start and start > end:
        raise ValueError("start must not be after end")
    if start and max_years and int(end[:4]) - int(start[:4]) + 1 > max_years:
        raise ValueError(f"Date range cannot exceed {max_years} calendar years.")
    return start, end


def _year(value, name="year"):
    raw = request.args.get(name, str(value))
    try:
        result = int(raw)
    except (TypeError, ValueError) as ex:
        raise ValueError(f"{name} must be a whole year from 1990 to 2100") from ex
    if not 1990 <= result <= 2100:
        raise ValueError(f"{name} must be a whole year from 1990 to 2100")
    return result


def _int_arg(name, default, lo, hi):
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as ex:
        raise ValueError(f"{name} must be a whole number from {lo} to {hi}") from ex
    return min(max(value, lo), hi)


@bp.app_errorhandler(ValueError)
def _bad(e):
    return jsonify({"error": str(e)}), 400


@bp.app_errorhandler(KeyError)
def _missing(e):
    return jsonify({"error": str(e).strip("'\"")}), 404


@bp.route("/api/health")
def health():
    c = db.connect()
    v = c.execute("PRAGMA user_version").fetchone()[0]
    c.close()
    return jsonify({"status": "ok", "schema_version": v, "firms_key_configured": bool(KEY())})


@bp.route("/api/regions")
def regions():
    c = db.connect()
    r = [dict(x) for x in c.execute("SELECT * FROM regions")]
    c.close()
    return jsonify(r)


@bp.route("/api/overview")
def overview():
    scope, region = _scope_region()
    c, sc = db.connect(), db.scope_clause(scope)
    reg = analytics.get_region(c, region)
    spatial_args = analytics.box(reg)
    rows = [dict(r) for r in c.execute(f"SELECT origin,sensor,satellite,COUNT(*) n,MIN(acq_date) first,MAX(acq_date) last,"
                                       f"AVG(frp) frp_mean,MAX(frp) frp_max FROM satellite_observations WHERE {sc} "
                                       "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? GROUP BY origin,sensor,satellite", spatial_args)]
    origin_filter = "origin='demo'" if scope == "demo" else "origin!='demo'"
    imps = [dict(r) for r in c.execute(f"SELECT * FROM data_imports WHERE {origin_filter} ORDER BY id DESC LIMIT 8")]
    prov = [dict(r) for r in c.execute(f"SELECT s.origin origin,COUNT(*) links FROM observation_sources s JOIN satellite_observations o "
                                       f"ON o.id=s.observation_id WHERE o.{sc} AND o.lat BETWEEN ? AND ? AND o.lon BETWEEN ? AND ? GROUP BY s.origin", spatial_args)]
    out = {"scope": scope, "region": region, "provenance": prov, "by_source": rows, "total": sum(r["n"] for r in rows),
           "totals": {s: sum(r["n"] for r in rows if r["sensor"] == s) for s in ("MODIS", "VIIRS")},
           "coverage": analytics.coverage_ranges(c, scope, reg), "imports": imps,
           "years": sorted({int(r["first"][:4]) for r in rows} | {int(r["last"][:4]) for r in rows}) if rows else []}
    out["years"] = list(range(min(out["years"]), max(out["years"]) + 1)) if out["years"] else []
    c.close()
    return jsonify(out)


@bp.route("/api/map/observations")
def map_obs():
    scope, region = _scope_region()
    c, sc = db.connect(), db.scope_clause(scope)
    reg = analytics.get_region(c, region)
    s, n, w, e = analytics.box(reg)
    if request.args.get("bbox"):
        try:
            w, s, e, n = db.validate_bbox(*request.args["bbox"].split(","))
        except (TypeError, ValueError) as ex:
            raise ValueError(f"bbox must be four valid coordinates: {ex}") from ex
    q, a = f"{sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", [s, n, w, e]
    start, end = _date_range()
    if start:
        q, a = q + " AND acq_date>=? AND acq_date<=?", a + [start, end]
    since = request.args.get("since")
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                raise ValueError
            since = since_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as ex:
            raise ValueError("since must be an ISO timestamp with a timezone") from ex
        q, a = q + " AND acq_utc>=?", a + [since]
    raw_sensors = request.args.get("sensor", "MODIS,VIIRS").split(",")
    sensors = [x.strip() for x in raw_sensors]
    if not sensors or any(x not in ("MODIS", "VIIRS") for x in sensors):
        raise ValueError("sensor must be a comma-separated list containing MODIS and/or VIIRS")
    q, a = q + f" AND sensor IN ({','.join('?' * len(sensors))})", a + sensors
    if request.args.get("satellite"):
        q, a = q + " AND satellite=?", a + [request.args["satellite"]]
    limit = _int_arg("limit", 5000, 100, 20000)
    total = c.execute(f"SELECT COUNT(*) FROM satellite_observations WHERE {q}", a).fetchone()[0]
    k = max(1, math.ceil(total / limit))  # uniform thinning by id, not deduplication
    rows = c.execute(f"WITH matching AS (SELECT id,sensor,satellite,acq_utc,lat,lon,frp,confidence_raw,origin,"
                     f"ROW_NUMBER() OVER (ORDER BY acq_utc,id) AS sample_n FROM satellite_observations WHERE {q}) "
                     f"SELECT id,sensor,satellite,acq_utc,lat,lon,frp,confidence_raw,origin FROM matching "
                     f"WHERE (sample_n - 1) % ? = 0 ORDER BY sample_n LIMIT ?", a + [k, limit]).fetchall()
    c.close()
    return jsonify({"scope": scope, "total_matching": total, "returned": len(rows), "thinned_every": k,
                    "observations": [dict(r) for r in rows]})


@bp.route("/api/activity")
def activity():
    """Observed detections by hour/day; uncovered buckets are null, never invented zeros."""
    scope, region_id = _scope_region()
    period = request.args.get("range", "30d")
    sensors = [sensor.strip() for sensor in request.args.get("sensor", "MODIS,VIIRS").split(",")]
    if not sensors or any(sensor not in ("MODIS", "VIIRS") for sensor in sensors) or len(set(sensors)) != len(sensors):
        raise ValueError("sensor must be a comma-separated list containing MODIS and/or VIIRS")
    now = datetime.now(timezone.utc)
    if period == "24h":
        hourly = True
        window_start = now - timedelta(hours=24)
        first = window_start.replace(minute=0, second=0, microsecond=0)
        last_hour = now.replace(minute=0, second=0, microsecond=0)
        start, end = window_start.date().isoformat(), now.date().isoformat()
        bucket_count = int((last_hour - first).total_seconds() // 3600) + 1
        buckets = [first + timedelta(hours=i) for i in range(bucket_count)]
        sql_group = "substr(acq_utc,1,13) || ':00:00Z'"
        start_utc, end_utc = window_start.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif period in ("7d", "30d", "90d"):
        hourly = False
        days = int(period[:-1])
        first_day = now.date() - timedelta(days=days - 1)
        start, end = first_day.isoformat(), now.date().isoformat()
        buckets = [first_day + timedelta(days=i) for i in range(days)]
        sql_group = "acq_date"
        start_utc, end_utc = start + "T00:00:00Z", end + "T23:59:59Z"
    elif period == "custom":
        hourly = False
        start, end = _date_range(require_both=True)
        first_day, last_day = date.fromisoformat(start), date.fromisoformat(end)
        if last_day < first_day or last_day - first_day > timedelta(days=364):
            raise ValueError("Custom activity range must be between 1 and 365 days")
        if last_day > now.date():
            raise ValueError("Activity end date cannot be in the future")
        days = (last_day - first_day).days + 1
        buckets = [first_day + timedelta(days=i) for i in range(days)]
        sql_group = "acq_date"
        start_utc, end_utc = start + "T00:00:00Z", end + "T23:59:59Z"
    else:
        raise ValueError("range must be 24h, 7d, 30d, 90d or custom")

    c = db.connect()
    reg, sc = analytics.get_region(c, region_id), db.scope_clause(scope)
    w, s, e, n = reg["west"], reg["south"], reg["east"], reg["north"]
    rows = c.execute(
        f"SELECT {sql_group} bucket,sensor,COUNT(*) total,"
        "SUM(CASE WHEN (sensor='MODIS' AND CAST(confidence_raw AS REAL)>=80) "
        "OR (sensor='VIIRS' AND lower(trim(confidence_raw)) IN ('h','high')) THEN 1 ELSE 0 END) high "
        f"FROM satellite_observations WHERE {sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "AND acq_utc BETWEEN ? AND ? AND sensor IN (" + ",".join("?" for _ in sensors) + ") GROUP BY bucket,sensor",
        (s, n, w, e, start_utc, end_utc, *sensors),
    ).fetchall()
    observed = {(r["bucket"], r["sensor"]): (r["total"], r["high"]) for r in rows}
    coverage = analytics.coverage_ranges(c, scope, reg)
    series = []
    for bucket in buckets:
        label = bucket.strftime("%Y-%m-%dT%H:00:00Z") if hourly else bucket.isoformat()
        item = {"date": label}
        day = label[:10]
        for sensor, key in (("MODIS", "modis"), ("VIIRS", "viirs")):
            value = observed.get((label, sensor))
            state = analytics.cov_state(coverage[sensor], day)
            item[key] = value[0] if value else (0 if sensor in sensors and state == "confirmed" else None)
            item[key + "_high"] = value[1] if value else (0 if sensor in sensors and state == "confirmed" else None)
        series.append(item)

    total = sum(r["total"] for r in rows)
    high = sum(r["high"] for r in rows)
    regions = c.execute("SELECT * FROM regions").fetchall()
    active_regions = 0
    for candidate in regions:
        count = c.execute(
            f"SELECT 1 FROM satellite_observations WHERE {sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
            "AND acq_utc BETWEEN ? AND ? AND sensor IN (" + ",".join("?" for _ in sensors) + ") LIMIT 1",
            (candidate["south"], candidate["north"], candidate["west"], candidate["east"], start_utc, end_utc, *sensors),
        ).fetchone()
        active_regions += bool(count)
    latest = c.execute(
        f"SELECT MAX(acq_utc) FROM satellite_observations WHERE {sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "AND acq_utc BETWEEN ? AND ? AND sensor IN (" + ",".join("?" for _ in sensors) + ")",
        (s, n, w, e, start_utc, end_utc, *sensors),
    ).fetchone()[0]
    c.close()
    return jsonify({"scope": scope, "region": region_id, "range": period, "granularity": "hour" if hourly else "day",
                    "start": start, "end": end, "start_utc": start_utc, "sensors": sensors, "series": series,
                    "summary": {"total": total, "high_confidence": high, "active_regions": active_regions,
                                "latest_observation": latest},
                    "confidence_note": "High confidence means MODIS raw confidence ≥80 or VIIRS raw confidence h/high; these sensor scales are not equivalent."})


@bp.post("/api/import")
def api_import():
    f = request.files.get("file")
    if not f or not f.filename:
        raise ValueError("Choose a CSV, JSON or GeoJSON file.")
    if not f.filename.lower().endswith((".csv", ".json", ".geojson")):
        raise ValueError("Supported archive formats are CSV, JSON and GeoJSON.")
    sensor = request.form.get("sensor") or None
    if sensor not in (None, "MODIS", "VIIRS"):
        raise ValueError("sensor must be MODIS or VIIRS")
    cs, ce = request.form.get("coverage_start") or None, request.form.get("coverage_end") or None
    for label, value in (("coverage_start", cs), ("coverage_end", ce)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError as ex:
                raise ValueError(f"{label} must be a real date in YYYY-MM-DD format") from ex
    if bool(cs) != bool(ce):
        raise ValueError("Provide both coverage dates or neither.")
    if cs and cs > ce:
        raise ValueError("Coverage start must not be after coverage end.")
    if not _IMPORT_SLOTS.acquire(blocking=False):
        return jsonify({"error": "Two imports are already running. Wait for one to finish, then retry."}), 429
    iid = None
    try:  # geographical extent is required and must be declared; it is never inferred from the detections
        safe_name = secure_filename(f.filename) or "archive-upload"
        content = f.read()
        c = db.connect()
        try:
            bbox, label = importer.resolve_extent(c, request.form.get("extent", ""), [request.form.get(k) for k in ("west", "south", "east", "north")])
            iid = importer.create_import(c, safe_name, "nasa_archive", bbox=bbox, extent_label=label)
        finally:
            c.close()
        worker = threading.Thread(target=_background_import,
                                  args=(safe_name, content, "nasa_archive", sensor, cs, ce, iid, bbox, label), daemon=True)
        worker.start()
    except Exception as ex:
        _IMPORT_SLOTS.release()
        if iid:
            c = db.connect()
            try:
                c.execute("UPDATE data_imports SET status='error',error=?,finished_at=? WHERE id=?",
                          ("Could not start import worker: " + str(ex)[:240], db.now(), iid))
                c.commit()
            finally:
                c.close()
            return jsonify({"error": "The upload was received, but its import worker could not start."}), 503
        raise
    return jsonify({"import_id": iid}), 202


@bp.route("/api/imports")
def imports():
    c = db.connect()
    r = [dict(x) for x in c.execute("SELECT * FROM data_imports ORDER BY id DESC LIMIT 50")]
    c.close()
    return jsonify(r)


@bp.route("/api/imports/<int:iid>")
def import_status(iid):
    c = db.connect()
    r = c.execute("SELECT * FROM data_imports WHERE id=?", (iid,)).fetchone()
    c.close()
    if not r:
        raise KeyError("Import not found")
    return jsonify(dict(r))


@bp.post("/api/imports/<int:iid>/extent")
def set_extent(iid):
    """Declare the geographical extent of an existing import (for example one made before extents were required)."""
    body = request.get_json(silent=True) or request.form
    c = db.connect()
    try:
        if not c.execute("SELECT 1 FROM data_imports WHERE id=?", (iid,)).fetchone():
            raise KeyError("Import not found")
        bbox, label = importer.resolve_extent(c, body.get("extent", ""), [body.get(k) for k in ("west", "south", "east", "north")])
        c.execute("UPDATE data_imports SET bbox=?,extent_label=? WHERE id=?", (json.dumps(bbox), label, iid))
        c.commit()
    finally:
        c.close()
    return jsonify({"import_id": iid, "bbox": bbox, "extent_label": label})


@bp.route("/api/observations/<int:oid>/sources")
def observation_sources(oid):
    c = db.connect()
    o = c.execute("SELECT * FROM satellite_observations WHERE id=?", (oid,)).fetchone()
    if not o:
        c.close()
        raise KeyError("Observation not found")
    src = [dict(r) for r in c.execute("SELECT s.import_id,s.origin,s.source_ref,s.version,s.confidence_raw,s.frp,s.platform_raw,s.raw_record,i.filename,i.source_name "
                                      "FROM observation_sources s JOIN data_imports i ON i.id=s.import_id WHERE s.observation_id=? "
                                      "ORDER BY s.import_id", (oid,))]
    c.close()
    return jsonify({"observation": dict(o), "sources": src})


@bp.post("/api/nrt/refresh")
def nrt_refresh():
    if not KEY():
        return jsonify({"error": "FIRMS_MAP_KEY is not set on the server. Live NASA retrieval is unavailable."}), 400
    days = _int_arg("days", 3, 1, 5)
    res = importer.ingest_nrt(KEY(), days)
    failed = [r["source"] for r in res if r["status"] == "error"]
    return jsonify({"results": res, "retrieved_at": db.now(), "partial_failure": bool(failed), "failed_sources": failed,
                    "status": "error" if len(failed) == len(res) else "partial" if failed else "ok"})


@bp.post("/api/demo/load")
def demo_load():
    return jsonify({"import_id": demo_data.load(), "label": "SYNTHETIC demonstration data, not NASA observations"})


@bp.route("/api/demo", methods=["DELETE"])
def demo_clear():
    c = db.connect()
    runs = [r[0] for r in c.execute("SELECT id FROM processing_runs WHERE scope='demo'")]
    for rid in runs:
        c.execute("DELETE FROM harmonization_matches WHERE run_id=?", (rid,))
        c.execute("DELETE FROM correspondence_groups WHERE run_id=?", (rid,))
    c.execute("DELETE FROM processing_runs WHERE scope='demo'")
    c.execute("DELETE FROM satellite_observations WHERE scope='demo'")  # source links cascade
    c.execute("DELETE FROM data_imports WHERE origin='demo'")
    analytics.rebuild_activity(c, "demo")
    c.close()
    return jsonify({"cleared": True})


@bp.route("/api/calendar")
def calendar():
    scope, region = _scope_region()
    metric = request.args.get("metric", "viirs")
    if metric not in ("modis", "viirs", "sum"):
        raise ValueError("metric must be modis, viirs or sum")
    c = db.connect()
    r = analytics.calendar_view(c, scope, region, _year(date.today().year), metric)
    c.close()
    return jsonify(r)


@bp.route("/api/monthly")
def monthly():
    scope, region = _scope_region()
    raw_years = request.args.get("years", str(date.today().year))
    try:
        years = sorted({int(y.strip()) for y in raw_years.split(",")})
    except ValueError as ex:
        raise ValueError("years must be comma-separated whole years from 1990 to 2100") from ex
    if not years or any(y < 1990 or y > 2100 for y in years):
        raise ValueError("years must be comma-separated whole years from 1990 to 2100")
    if len(years) > 20:
        raise ValueError("Request no more than 20 years at a time")
    c = db.connect()
    r = analytics.monthly_view(c, scope, region, years)
    c.close()
    return jsonify({"months": r})


@bp.route("/api/anomalies")
def anomalies():
    scope, region = _scope_region()
    level, sensor = request.args.get("level", "monthly"), request.args.get("sensor", "VIIRS").upper()
    if level not in ("monthly", "daily") or sensor not in ("MODIS", "VIIRS"):
        raise ValueError("level must be monthly|daily and sensor MODIS|VIIRS")
    c = db.connect()
    r = analytics.anomalies(c, scope, region, sensor, level, _int_arg("min_years", 3, 2, 20))
    c.close()
    return jsonify(r)


@bp.post("/api/harmonize")
def harmonize_run():
    scope, region = _scope_region()
    start, end = _date_range(require_both=True, max_years=50)
    c = db.connect()
    try:
        r = analytics.run_harmonization(c, scope, region, start, end, _num("dist", 1000, 100, 5000), _num("dt", 120, 0, 720))
    finally:
        c.close()
    return jsonify({"scope": scope, **r})


@bp.route("/api/comparison")
def comparison():
    scope, region = _scope_region()
    start, end = _date_range(max_years=50)
    c, sc = db.connect(), db.scope_clause(scope)
    reg = analytics.get_region(c, region)
    q, a = f"{sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", list(analytics.box(reg))
    if start:
        q, a = q + " AND acq_date BETWEEN ? AND ?", a + [start, end]
    daily = {}
    for r in c.execute(f"SELECT acq_date d,sensor s,COUNT(*) n FROM satellite_observations WHERE {q} GROUP BY d,s", a):
        daily.setdefault(r["d"], {"MODIS": 0, "VIIRS": 0})[r["s"]] = r["n"]
    edges = [0, 1, 2, 5, 10, 20, 50, 100, 200, 500]
    hist = {}
    for s in ("MODIS", "VIIRS"):
        cnt = [0] * len(edges)
        for (f,) in c.execute(f"SELECT frp FROM satellite_observations WHERE {q} AND sensor=? AND frp IS NOT NULL LIMIT 300000", a + [s]):
            cnt[max(i for i, e in enumerate(edges) if f >= e)] += 1
        hist[s] = cnt
    run = c.execute("SELECT * FROM processing_runs WHERE kind='harmonization' AND scope=? AND region_id=? ORDER BY id DESC LIMIT 1",
                    (scope, region)).fetchone()
    c.close()
    return jsonify({"scope": scope, "daily": [{"date": d, **v} for d, v in sorted(daily.items())], "frp_bins": edges, "frp_hist": hist,
                    "last_run": {"id": run["id"], "start": run["start_date"], "end": run["end_date"], "params": json.loads(run["params"]),
                                 "summary": json.loads(run["summary"])} if run else None})


@bp.route("/api/regions/summary")
def regions_summary():
    scope, _ = _scope_region()
    start, end = _date_range(max_years=50)
    c, sc, out = db.connect(), db.scope_clause(scope), []
    for reg in c.execute("SELECT * FROM regions").fetchall():
        q, a = f"{sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", list(analytics.box(reg))
        if start:
            q, a = q + " AND acq_date BETWEEN ? AND ?", a + [start, end]
        cnt = {r["sensor"]: r["n"] for r in c.execute(f"SELECT sensor,COUNT(*) n FROM satellite_observations WHERE {q} GROUP BY sensor", a)}
        out.append({"id": reg["id"], "name": reg["name"], "modis": cnt.get("MODIS", 0), "viirs": cnt.get("VIIRS", 0)})
    c.close()
    return jsonify({"scope": scope, "regions": sorted(out, key=lambda r: -r["viirs"])})


@bp.route("/api/reports/export")
def export():
    scope, region = _scope_region()
    start, end = _date_range(require_both=True, max_years=50)
    fmt = request.args.get("format", "csv")
    if fmt not in ("csv", "html"):
        raise ValueError("format must be csv or html")
    c = db.connect()
    reg = analytics.get_region(c, region)
    spatial = "lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
    region_args = list(analytics.box(reg))
    days = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        days += [d for d in analytics.calendar_view(c, scope, region, y)["days"] if start <= d["date"] <= end]
    org = [dict(r) for r in c.execute(f"SELECT origin,sensor,satellite,COUNT(*) n FROM satellite_observations WHERE {db.scope_clause(scope)} "
                                      f"AND {spatial} AND acq_date BETWEEN ? AND ? GROUP BY origin,sensor,satellite", (*region_args, start, end))]
    months = [m for m in analytics.monthly_view(c, scope, region, range(int(start[:4]), int(end[:4]) + 1))
              if start[:7] <= m["month"] <= end[:7]]
    run = c.execute("SELECT * FROM processing_runs WHERE kind='harmonization' AND scope=? AND region_id=? "
                    "AND start_date<=? AND end_date>=? ORDER BY id DESC LIMIT 1", (scope, region, end, start)).fetchone()
    imports = []
    import_scope = "origin='demo'" if scope == "demo" else "origin!='demo'"
    for im in c.execute("SELECT id,filename,source_name,origin,coverage_start,coverage_end,coverage_assumed,extent_label,bbox,started_at,finished_at "
                        f"FROM data_imports WHERE status='done' AND {import_scope} AND coverage_start<=? AND coverage_end>=? ORDER BY id", (end, start)):
        if not im["bbox"]:
            continue
        west, south, east, north = json.loads(im["bbox"])
        if west <= reg["west"] and south <= reg["south"] and east >= reg["east"] and north >= reg["north"]:
            imports.append(dict(im))
    c.close()
    label = "SYNTHETIC DEMONSTRATION DATA (not NASA observations)" if scope == "demo" else "NASA FIRMS data (live NRT and/or user-imported archive exports)"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    qual = {s: Counter(d[s]["status"] for d in days) for s in ("modis", "viirs")}
    cq = "; ".join(f"{s.upper()}: {n['active']} active, {n['confirmed_zero']} confirmed-zero, {n['assumed_coverage']} assumed-coverage "
                   f"(zero NOT confirmed), {n['no_data']} no-data day(s)" for s, n in qual.items())
    note = "Counts are satellite detections, not individual fires. FRP is reported per sensor and is not merged. Blank = no data loaded for that day."
    if fmt == "csv":
        lines = [f"# AgniLens export | {label} | region: {reg['name']} (approximate box) | {start} to {end} | generated {stamp}", f"# {note}", f"# Coverage quality: {cq}",
                 "# Import IDs, datasets, coverage and retrieval timestamps:"]
        lines.extend(f"# import={i['id']} source={i['source_name'] or i['filename']} origin={i['origin']} coverage={i['coverage_start']}..{i['coverage_end']} "
                     f"quality={'assumed' if i['coverage_assumed'] else 'declared'} extent={i['extent_label']} started={i['started_at']} finished={i['finished_at']}" for i in imports)
        lines.append("# Harmonization run: " + (f"id={run['id']} parameters={run['params']} summary={run['summary']}" if run else "none for this period"))
        lines.append("# Monthly detections (raw satellite counts; no cross-sensor FRP merge):")
        lines.extend(f"# month={m['month']} MODIS={m['modis']['count'] if m['modis']['count'] is not None else 'no_data'} VIIRS={m['viirs']['count'] if m['viirs']['count'] is not None else 'no_data'}" for m in months)
        lines.append("date,modis_status,modis_count,modis_frp_mean,modis_frp_max,viirs_status,viirs_count,viirs_frp_mean,viirs_frp_max,candidate_pairs,candidate_groups")
        for d in days:
            f = lambda s, k: "" if d[s].get(k) is None else d[s][k]
            lines.append(",".join(str(x) for x in [d["date"], d["modis"]["status"], f("modis", "count"), f("modis", "frp_mean"), f("modis", "frp_max"),
                                                    d["viirs"]["status"], f("viirs", "count"), f("viirs", "frp_mean"), f("viirs", "frp_max"),
                                                    "" if d["candidate_pairs"] is None else d["candidate_pairs"],
                                                    "" if d["candidate_groups"] is None else d["candidate_groups"]]))
        return Response("\n".join(lines) + "\n", mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=agnilens_{region}_{start}_{end}.csv"})
    e = html.escape
    rows = "".join(f"<tr><td>{e(r['origin'])}</td><td>{r['sensor']}</td><td>{e(str(r['satellite']))}</td><td>{r['n']}</td></tr>" for r in org)
    import_rows = "".join(f"<tr><td>{r['id']}</td><td>{e(r['source_name'] or r['filename'])}</td><td>{e(r['origin'])}</td>"
                          f"<td>{r['coverage_start']} to {r['coverage_end']} ({'assumed' if r['coverage_assumed'] else 'declared'})</td>"
                          f"<td>{e(r['extent_label'] or 'extent unavailable')}</td><td>{e(r['started_at'] or '')}</td><td>{e(r['finished_at'] or '')}</td></tr>" for r in imports)
    mrows = "".join(f"<tr><td>{m['month']}</td><td>{m['modis']['count'] if m['modis']['count'] is not None else 'no data'}</td>"
                    f"<td>{m['viirs']['count'] if m['viirs']['count'] is not None else 'no data'}</td></tr>" for m in months)
    body = (f"<h1>AgniLens regional report</h1><p><b>Data source:</b> {e(label)}</p><p><b>Region:</b> {e(reg['name'])} (approximate bounding box)<br>"
            f"<b>Period:</b> {start} to {end}<br><b>Generated:</b> {stamp}</p><p><b>Coverage quality:</b> {e(cq)}</p><h2>Observations by source</h2><table><tr><th>Origin</th><th>Sensor</th>"
            f"<th>Satellite</th><th>Detections</th></tr>{rows}</table><h2>Source imports and retrieval times (UTC)</h2><table><tr><th>ID</th><th>Dataset</th><th>Origin</th><th>Coverage</th><th>Extent</th><th>Started</th><th>Finished</th></tr>{import_rows}</table>"
            f"<h2>Monthly detections</h2><table><tr><th>Month</th><th>MODIS</th><th>VIIRS</th></tr>{mrows}</table>"
            f"<h2>Harmonization</h2><p>{e('No saved harmonization run overlaps this report period.') if not run else 'Run '+str(run['id'])+' parameters '+e(run['params'])+' summary '+e(run['summary'])}</p>"
            f"<h2>Methodology and limitations</h2><ul><li>{e(note)}</li><li>MODIS (about 1 km) and VIIRS (375 m) differ in resolution, overpass times and confidence scales.</li>"
            "<li>Cross-sensor matches are candidate correspondences by distance and time, not verified identical fires.</li><li>Regions are approximate boxes, not administrative boundaries.</li></ul>")
    return Response(f"<!doctype html><meta charset=utf-8><title>AgniLens report</title><style>body{{font-family:system-ui;max-width:820px;margin:30px auto;padding:0 16px}}"
                    f"table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:5px;text-align:left}}</style>{body}", mimetype="text/html")


