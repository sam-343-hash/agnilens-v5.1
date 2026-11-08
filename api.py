"""AgniLens JSON API. FIRMS_MAP_KEY stays server-side; never returned to the browser."""
import html, json, logging, math, os, threading
from collections import Counter
from datetime import date, datetime, timezone

from flask import Blueprint, Response, jsonify, request

import analytics, db, demo_data, importer

log = logging.getLogger("agnilens.api")
bp = Blueprint("agnilens", __name__)
KEY = lambda: os.getenv("FIRMS_MAP_KEY", "")


def _scope_region():
    scope = request.args.get("scope", "nasa")
    if scope not in ("nasa", "demo"):
        raise ValueError("scope must be 'nasa' or 'demo'")
    return scope, request.args.get("region", "in-pb-hr")


def _d(name, default=None):
    v = request.args.get(name, default)
    if v:
        datetime.strptime(v, "%Y-%m-%d")
    return v


def _num(name, default, lo, hi):
    try:
        return min(max(float(request.args.get(name, default)), lo), hi)
    except ValueError:
        raise ValueError(f"{name} must be a number")


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
    rows = [dict(r) for r in c.execute(f"SELECT origin,sensor,satellite,COUNT(*) n,MIN(acq_date) first,MAX(acq_date) last,"
                                       f"AVG(frp) frp_mean,MAX(frp) frp_max FROM satellite_observations WHERE {sc} GROUP BY origin,sensor,satellite")]
    imps = [dict(r) for r in c.execute("SELECT * FROM data_imports ORDER BY id DESC LIMIT 30") if (r["origin"] == "demo") == (scope == "demo")][:8]
    reg = analytics.get_region(c, region)
    prov = [dict(r) for r in c.execute(f"SELECT s.origin origin,COUNT(*) links FROM observation_sources s JOIN satellite_observations o "
                                       f"ON o.id=s.observation_id WHERE o.{sc} GROUP BY s.origin")]
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
    if _d("start"):
        q, a = q + " AND acq_date>=?", a + [request.args["start"]]
    if _d("end"):
        q, a = q + " AND acq_date<=?", a + [request.args["end"]]
    sensors = [x for x in request.args.get("sensor", "MODIS,VIIRS").split(",") if x in ("MODIS", "VIIRS")] or ["MODIS", "VIIRS"]
    q, a = q + f" AND sensor IN ({','.join('?' * len(sensors))})", a + sensors
    if request.args.get("satellite"):
        q, a = q + " AND satellite=?", a + [request.args["satellite"]]
    limit = int(_num("limit", 5000, 100, 20000))
    total = c.execute(f"SELECT COUNT(*) FROM satellite_observations WHERE {q}", a).fetchone()[0]
    k = max(1, math.ceil(total / limit))  # uniform thinning by id, not deduplication
    rows = c.execute(f"SELECT id,sensor,satellite,acq_utc,lat,lon,frp,confidence_raw,origin FROM satellite_observations WHERE {q}"
                     f"{' AND id % ? = 0' if k > 1 else ''} LIMIT ?", a + ([k] if k > 1 else []) + [limit]).fetchall()
    c.close()
    return jsonify({"scope": scope, "total_matching": total, "returned": len(rows), "thinned_every": k,
                    "observations": [dict(r) for r in rows]})


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
    for v in (cs, ce):
        if v:
            datetime.strptime(v, "%Y-%m-%d")
    if bool(cs) != bool(ce):
        raise ValueError("Provide both coverage dates or neither.")
    if cs and cs > ce:
        raise ValueError("Coverage start must not be after coverage end.")
    c = db.connect()
    try:  # geographical extent is required and must be declared; it is never inferred from the detections
        bbox, label = importer.resolve_extent(c, request.form.get("extent", ""), [request.form.get(k) for k in ("west", "south", "east", "north")])
        content = f.read()
        iid = importer.create_import(c, f.filename, "nasa_archive", bbox=bbox, extent_label=label)
    finally:
        c.close()
    threading.Thread(target=importer.import_file, args=(f.filename, content, "nasa_archive", sensor, cs, ce, iid, bbox, label), daemon=True).start()
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
    days = int(_num("days", 3, 1, 5))
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
    r = analytics.calendar_view(c, scope, region, int(_num("year", date.today().year, 1990, 2100)), metric)
    c.close()
    return jsonify(r)


@bp.route("/api/monthly")
def monthly():
    scope, region = _scope_region()
    years = [int(y) for y in request.args.get("years", str(date.today().year)).split(",") if y.strip().isdigit()]
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
    r = analytics.anomalies(c, scope, region, sensor, level, int(_num("min_years", 3, 2, 20)))
    c.close()
    return jsonify(r)


@bp.post("/api/harmonize")
def harmonize_run():
    scope, region = _scope_region()
    start, end = _d("start"), _d("end")
    if not (start and end):
        raise ValueError("start and end dates are required (YYYY-MM-DD)")
    if start > end:
        raise ValueError("start must not be after end")
    c = db.connect()
    try:
        r = analytics.run_harmonization(c, scope, region, start, end, _num("dist", 1000, 100, 5000), _num("dt", 120, 0, 720))
    finally:
        c.close()
    return jsonify({"scope": scope, **r})


@bp.route("/api/comparison")
def comparison():
    scope, region = _scope_region()
    start, end = _d("start"), _d("end")
    c, sc = db.connect(), db.scope_clause(scope)
    reg = analytics.get_region(c, region)
    q, a = f"{sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", list(analytics.box(reg))
    if start and end:
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
    start, end = _d("start"), _d("end")
    c, sc, out = db.connect(), db.scope_clause(scope), []
    for reg in c.execute("SELECT * FROM regions").fetchall():
        q, a = f"{sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", list(analytics.box(reg))
        if start and end:
            q, a = q + " AND acq_date BETWEEN ? AND ?", a + [start, end]
        cnt = {r["sensor"]: r["n"] for r in c.execute(f"SELECT sensor,COUNT(*) n FROM satellite_observations WHERE {q} GROUP BY sensor", a)}
        out.append({"id": reg["id"], "name": reg["name"], "modis": cnt.get("MODIS", 0), "viirs": cnt.get("VIIRS", 0)})
    c.close()
    return jsonify({"scope": scope, "regions": sorted(out, key=lambda r: -r["viirs"])})


@bp.route("/api/reports/export")
def export():
    scope, region = _scope_region()
    start, end, fmt = _d("start"), _d("end"), request.args.get("format", "csv")
    if not (start and end):
        raise ValueError("start and end dates are required")
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
    for im in c.execute("SELECT id,filename,source_name,origin,coverage_start,coverage_end,coverage_assumed,extent_label,bbox,started_at,finished_at "
                        "FROM data_imports WHERE status='done' AND coverage_start<=? AND coverage_end>=? ORDER BY id", (end, start)):
        if (im["origin"] == "demo") != (scope == "demo") or not im["bbox"]:
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


