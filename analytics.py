"""Aggregation, calendar, anomaly and DB-backed harmonization logic. Counts are detections, not fires."""
import calendar as cal
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import db
import harmonize as H


def get_region(conn, rid):
    r = conn.execute("SELECT * FROM regions WHERE id=?", (rid,)).fetchone()
    if not r:
        raise KeyError(f"Unknown region: {rid}")
    return r


def box(reg):
    return (reg["south"], reg["north"], reg["west"], reg["east"])


def rebuild_activity(conn, scope):
    sc = db.scope_clause(scope)
    keep = {(r["region_id"], r["date"]): (r["candidate_pairs"], r["candidate_groups"]) for r in
            conn.execute("SELECT region_id,date,candidate_pairs,candidate_groups FROM daily_activity WHERE scope=?", (scope,))}
    conn.execute("DELETE FROM daily_activity WHERE scope=?", (scope,))
    conn.execute("DELETE FROM monthly_activity WHERE scope=?", (scope,))
    for reg in conn.execute("SELECT * FROM regions").fetchall():
        for table, expr in (("daily_activity", "acq_date"), ("monthly_activity", "substr(acq_date,1,7)")):
            agg = defaultdict(dict)
            for r in conn.execute(f"SELECT {expr} k,sensor,COUNT(*) c,AVG(frp) fm,MAX(frp) fx FROM satellite_observations "
                                  f"WHERE {sc} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? GROUP BY k,sensor", box(reg)):
                agg[r["k"]][r["sensor"]] = (r["c"], r["fm"], r["fx"])
            for k, v in agg.items():
                m, w = v.get("MODIS", (0, None, None)), v.get("VIIRS", (0, None, None))
                vals = [scope, reg["id"], k, m[0], w[0], m[1], m[2], w[1], w[2]]
                if table == "daily_activity":
                    conn.execute("INSERT INTO daily_activity VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 vals + list(keep.get((reg["id"], k), (None, None))))
                else:
                    conn.execute("INSERT INTO monthly_activity VALUES(?,?,?,?,?,?,?,?,?)", vals)
    conn.commit()


SENSORS = ("MODIS", "VIIRS")


def coverage_ranges(conn, scope, reg):
    """sensor -> [(start, end, confirmed)] from finished imports whose DECLARED extent fully contains the region.
    Imports without a declared extent give no regional coverage: extent is never inferred from detections.
    confirmed=False means the date range was only assumed (first to last detection date)."""
    out = {"MODIS": [], "VIIRS": []}
    for im in conn.execute("SELECT * FROM data_imports WHERE status='done' AND coverage_start IS NOT NULL "
                           "AND coverage_end IS NOT NULL AND bbox IS NOT NULL"):
        if (im["origin"] == "demo") != (scope == "demo"):
            continue
        w, s, e, n = json.loads(im["bbox"])
        if not (w <= reg["west"] and s <= reg["south"] and e >= reg["east"] and n >= reg["north"]):
            continue
        for sen in (im["sensors"] or "").split(","):
            if sen in out:
                out[sen].append((im["coverage_start"], im["coverage_end"], not im["coverage_assumed"]))
    return out


def cov_state(ranges, day):
    """'confirmed' beats 'assumed'; None means no coverage information."""
    state = None
    for a, b, ok in ranges:
        if a <= day <= b:
            if ok:
                return "confirmed"
            state = "assumed"
    return state


def _level_thresholds(vals):
    nz = sorted(v for v in vals if v and v > 0)
    return [nz[min(len(nz) - 1, int(p * len(nz)))] for p in (.5, .75, .9)] if nz else []


def _metric(rec, metric):
    """-> (value, value_state). Only active or confirmed-zero days produce a value."""
    keys = ("modis", "viirs") if metric == "sum" else (metric,)
    sts = [rec[k]["status"] for k in keys]
    if "no_data" in sts:
        return None, "no_data"
    if "assumed_coverage" in sts:
        return None, "assumed_coverage"
    return sum(rec[k]["count"] for k in keys), ("active" if "active" in sts else "confirmed_zero")


def calendar_view(conn, scope, region_id, year, metric="viirs"):
    """Per-day, per-sensor status: active | confirmed_zero | assumed_coverage | no_data."""
    reg = get_region(conn, region_id)
    cov = coverage_ranges(conn, scope, reg)
    rows = {r["date"]: r for r in conn.execute("SELECT * FROM daily_activity WHERE scope=? AND region_id=? AND date LIKE ?",
                                               (scope, region_id, f"{year}-%"))}
    days, tally, d = [], {s: Counter() for s in SENSORS}, date(year, 1, 1)
    while d.year == year:
        ds, r, rec = d.isoformat(), rows.get(d.isoformat()), {"date": d.isoformat()}
        for s in ("modis", "viirs"):
            st = cov_state(cov[s.upper()], ds)
            tally[s.upper()][st or "none"] += 1
            c = (r[f"{s}_count"] if r else 0) or 0
            status = "active" if c else "confirmed_zero" if st == "confirmed" else "assumed_coverage" if st == "assumed" else "no_data"
            rec[s] = {"status": status, "coverage": st}
            if status != "no_data":
                rec[s].update(count=c, frp_mean=r[f"{s}_frp_mean"] if r else None, frp_max=r[f"{s}_frp_max"] if r else None)
        rec["candidate_pairs"] = r["candidate_pairs"] if r else None
        rec["candidate_groups"] = r["candidate_groups"] if r else None
        rec["value"], rec["value_state"] = _metric(rec, metric)
        days.append(rec)
        d += timedelta(days=1)
    th = _level_thresholds([x["value"] for x in days])
    for x in days:
        x["level"] = None if x["value"] is None else (0 if x["value"] == 0 else 1 + sum(x["value"] > t for t in th))
    summ = {s: {k: tally[s][k] for k in ("confirmed", "assumed", "none")} for s in SENSORS}
    warn = [f"{s}: {summ[s]['assumed']} day(s) rely on assumed coverage, so zero detections there are not confirmed."
            for s in SENSORS if summ[s]["assumed"]]
    return {"year": year, "metric": metric, "thresholds": th, "days": days, "coverage_summary": summ, "warnings": warn}


def monthly_view(conn, scope, region_id, years):
    """Monthly totals per sensor. coverage = fraction of days with CONFIRMED coverage; assumed coverage is reported
    separately and never counts toward baselines. Per-platform counts are kept for every month."""
    reg, sc = get_region(conn, region_id), db.scope_clause(scope)
    cov = coverage_ranges(conn, scope, reg)
    rows = {r["month"]: r for r in conn.execute("SELECT * FROM monthly_activity WHERE scope=? AND region_id=?", (scope, region_id))}
    plat = {s: defaultdict(dict) for s in SENSORS}
    for r in conn.execute(f"SELECT substr(acq_date,1,7) m,sensor,satellite,COUNT(*) n FROM satellite_observations WHERE {sc} "
                          "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? GROUP BY m,sensor,satellite", box(reg)):
        plat[r["sensor"]][r["m"]][r["satellite"]] = r["n"]
    out = []
    for y in years:
        for m in range(1, 13):
            key, n = f"{y}-{m:02d}", cal.monthrange(y, m)[1]
            item, r = {"month": key}, rows.get(key)
            for s in SENSORS:
                states = [cov_state(cov[s], f"{key}-{d:02d}") for d in range(1, n + 1)]
                conf, assum = states.count("confirmed") / n, states.count("assumed") / n
                quality = "confirmed" if conf >= 0.8 else "partial" if conf > 0 else "assumed_only" if assum > 0 else "no_data"
                k = s.lower()
                item[k] = {"coverage": round(conf, 3), "assumed_coverage": round(assum, 3), "quality": quality,
                           "count": ((r[f"{k}_count"] if r else 0) or 0) if conf else None,
                           "frp_mean": r[f"{k}_frp_mean"] if r else None, "frp_max": r[f"{k}_frp_max"] if r else None,
                           "platforms": dict(plat[s].get(key, {}))}
            out.append(item)
    return out


# ---- anomaly detection (simple, transparent baselines) -------------------------------------------
def _median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def score(x, base):
    """Standard z plus a robust z. Robust scale = max(1.4826*MAD, sqrt(median)): the sqrt term is a Poisson
    noise floor so tiny baselines of count data are not over-flagged (1.4826*MAD equals MAD/0.6745)."""
    n, mean = len(base), sum(base) / len(base)
    std = statistics.stdev(base) if n > 1 else 0.0
    med = _median(base)
    mad = _median([abs(b - med) for b in base])
    scale = max(1.4826 * mad, math.sqrt(max(med, 1)))
    return {"n": n, "mean": round(mean, 2), "median": med, "std": round(std, 2), "mad": mad,
            "z": round((x - mean) / std, 2) if std > 0 else None, "robust_scale": round(scale, 2),
            "robust_z": round((x - med) / scale, 2)}


def is_flagged(sc):
    return abs(sc["robust_z"]) >= 3.5, "robust (median/MAD with Poisson noise floor, threshold 3.5)"


def moving_average(vals, k=7):
    return [None if i < k - 1 or any(v is None for v in vals[i - k + 1:i + 1]) else round(sum(vals[i - k + 1:i + 1]) / k, 2)
            for i in range(len(vals))]


def platform_check(month, base_keys, platforms):
    """Compare the observed month's platform SET with baseline months (identities, not just how many)."""
    obs = frozenset(platforms.get(month) or ())
    sets = [frozenset(platforms.get(k) or ()) for k in base_keys]
    common, n_common = Counter(sets).most_common(1)[0]
    union = obs | common
    info = {"observed": sorted(obs), "baseline_common": sorted(common), "baseline_identical_fraction": round(n_common / len(sets), 2),
            "jaccard_vs_common": round(len(obs & common) / len(union), 2) if union else 1.0}
    msgs = []
    if obs != common:
        added, missing = sorted(obs - common), sorted(common - obs)
        msgs.append("The satellite platforms contributing this month differ from the most common baseline configuration"
                    + (f" (added: {', '.join(added)})" if added else "") + (f" (missing: {', '.join(missing)})" if missing else "")
                    + ", so counts are not directly comparable.")
    if n_common / len(sets) < 0.5:
        msgs.append("The baseline months themselves use different platform combinations.")
    return info, " ".join(msgs) or None


def monthly_anomalies(series, min_years=3, min_cov=0.8, platforms=None):
    """series: [{month:'YYYY-MM', count, coverage}] (coverage = CONFIRMED fraction). platforms: {month: {satellite: n}}."""
    by = {s["month"]: s for s in series}
    out = []
    for s in series:
        if s["count"] is None or s["coverage"] < min_cov:
            continue
        y, mm = s["month"][:4], s["month"][5:]
        base_keys = [k for k, o in by.items() if k[5:] == mm and k[:4] != y and o["count"] is not None and o["coverage"] >= min_cov]
        item = {"month": s["month"], "observed": s["count"], "baseline_years": len(base_keys)}
        if len(base_keys) < min_years:
            item.update(status="insufficient_baseline", flagged=False)
        else:
            sc = score(s["count"], [by[k]["count"] for k in base_keys])
            flag, method = is_flagged(sc)
            item.update(status="ok", flagged=flag, method=method, baseline=sc, direction="above" if s["count"] > sc["median"] else "below")
            if platforms is not None:
                info, msg = platform_check(s["month"], base_keys, platforms)
                item["constellation"] = info
                item["platform_counts"] = dict(platforms.get(s["month"]) or {})
                if msg:
                    item["caveat"] = msg
        out.append(item)
    return out


def daily_anomalies(daily, window=7, min_years=3):
    """daily: {'YYYY-MM-DD': count} for COVERED days only."""
    out = []
    for ds, x in daily.items():
        d = date.fromisoformat(ds)
        pool, years = [], set()
        for y in {date.fromisoformat(k).year for k in daily} - {d.year}:
            try:
                c = date(y, d.month, d.day)
            except ValueError:
                continue
            for off in range(-window, window + 1):
                v = daily.get((c + timedelta(days=off)).isoformat())
                if v is not None:
                    pool.append(v)
                    years.add(y)
        item = {"date": ds, "observed": x, "baseline_years": len(years)}
        if len(years) < min_years:
            item.update(status="insufficient_baseline", flagged=False)
        else:
            sc = score(x, pool)
            flag, method = is_flagged(sc)
            item.update(status="ok", flagged=flag, method=method, baseline=sc, direction="above" if x > sc["median"] else "below")
        out.append(item)
    return out


def anomalies(conn, scope, region_id, sensor, level="monthly", min_years=3):
    sensor, reg = sensor.upper(), get_region(conn, region_id)
    allr = coverage_ranges(conn, scope, reg)[sensor]
    cov = [(a, b) for a, b, ok in allr if ok]
    notes = ["Only confirmed coverage (declared extent and dates) is used. Assumed coverage is excluded from observed values and baselines.",
             "Counts from different satellite platform configurations are not directly comparable."]
    if level == "daily":
        notes.append("Daily scores do not check platform changes; see the monthly view for constellation caveats.")
    base = {"sensor": sensor, "region": reg["name"], "level": level, "scope": scope, "min_years": min_years, "notes": notes,
            "excluded_assumed_months": 0, "excluded_partial_months": 0}
    if not cov:
        if allr:
            return {**base, "status": "assumed_only", "items": [], "anomalies": [],
                    "message": f"Only assumed coverage exists for {sensor} in this region. Declare the coverage dates and geographical extent on import to enable anomaly analysis."}
        return {**base, "status": "no_coverage", "message": f"No {sensor} data with a declared extent has been imported for this region and data scope.",
                "items": [], "anomalies": []}
    ys = [int(a[:4]) for a, _, _ in allr] + [int(b[:4]) for _, b, _ in allr]  # span all coverage so excluded months can be reported
    if level == "monthly":
        mv = monthly_view(conn, scope, region_id, range(min(ys), max(ys) + 1))
        k = sensor.lower()
        series = [{"month": m["month"], "count": m[k]["count"], "coverage": m[k]["coverage"]} for m in mv]
        base["excluded_assumed_months"] = sum(1 for m in mv if m[k]["quality"] == "assumed_only")
        base["excluded_partial_months"] = sum(1 for m in mv if m[k]["quality"] == "partial")
        items = monthly_anomalies(series, min_years, platforms={m["month"]: m[k]["platforms"] for m in mv})
    else:
        counts = {r["date"]: r[f"{sensor.lower()}_count"] or 0 for r in conn.execute(
            "SELECT * FROM daily_activity WHERE scope=? AND region_id=?", (scope, region_id))}
        daily = {}
        for a, b in cov:
            d = date.fromisoformat(a)
            while d.isoformat() <= b:
                daily[d.isoformat()] = counts.get(d.isoformat(), 0)
                d += timedelta(days=1)
        items = daily_anomalies(daily, min_years=min_years)
    ok = [i for i in items if i["status"] == "ok"]
    for i in items:
        if i.get("flagged"):
            b = i["baseline"]
            i["explanation"] = (f"{sensor} recorded {i['observed']} detections, {i['direction']} the median of {b['median']} "
                                f"across {b['n']} comparable observations ({i['method']}). This describes observed satellite "
                                "detection counts, not a wildfire prediction.")
    return {**base, "status": "ok" if ok else "insufficient_baseline", "evaluated": len(ok), "insufficient": len(items) - len(ok),
            "message": None if ok else f"Need at least {min_years} comparable years of confirmed data to compute a reliable baseline.",
            "items": items if level == "monthly" else [], "anomalies": [i for i in items if i.get("flagged")]}


# ---- harmonization on stored observations ---------------------------------------------------------
class TooLarge(ValueError):
    pass


def run_harmonization(conn, scope, region_id, start, end, dist, dt, max_rows=30000):
    reg, sc = get_region(conn, region_id), db.scope_clause(scope)
    rows = conn.execute(f"SELECT * FROM satellite_observations WHERE {sc} AND acq_date BETWEEN ? AND ? AND lat BETWEEN ? AND ? "
                        "AND lon BETWEEN ? AND ? ORDER BY acq_utc LIMIT ?", (start, end, *box(reg), max_rows + 1)).fetchall()
    if len(rows) > max_rows:
        raise TooLarge(f"More than {max_rows} observations in this range. Choose a shorter period or smaller region.")
    modis, viirs = [], []
    for r in rows:
        o = {"id": f"{r['sensor']}:{r['id']}", "sensor": r["sensor"], "satellite": r["satellite"],
             "ts": datetime.strptime(r["acq_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), "lat": r["lat"],
             "lon": r["lon"], "frp": r["frp"], "brightness_k": r["brightness"], "confidence_raw": r["confidence_raw"],
             "confidence_class": H._conf_class(r["sensor"], r["confidence_raw"]), "grid": H.cell_id(r["lat"], r["lon"]),
             "flags": [f for f in (r["flags"] or "").split(",") if f]}
        (modis if r["sensor"] == "MODIS" else viirs).append(o)
    res = H.match(modis, viirs, dist, dt)
    run = conn.execute("INSERT INTO processing_runs(kind,scope,region_id,start_date,end_date,params,summary,started_at,finished_at) "
                       "VALUES('harmonization',?,?,?,?,?,?,?,?)", (scope, region_id, start, end, json.dumps(res["params"]),
                                                                  json.dumps(res["summary"]), db.now(), db.now()))
    rid, idx = run.lastrowid, {o["id"]: o for o in res["observations"]}
    gdate, gm = {}, defaultdict(lambda: [0, 0])
    for o in res["observations"]:
        if o["group_id"]:
            gm[o["group_id"]][0 if o["sensor"] == "MODIS" else 1] += 1
            gdate[o["group_id"]] = min(gdate.get(o["group_id"], "9"), o["ts"][:10])
    conn.executemany("INSERT INTO harmonization_matches(run_id,modis_id,viirs_id,distance_m,dt_min,group_id) VALUES(?,?,?,?,?,?)",
                     [(rid, int(p["modis_id"].split(":")[1]), int(p["viirs_id"].split(":")[1]), p["distance_m"], p["dt_min"],
                       idx[p["viirs_id"]]["group_id"]) for p in res["pairs"]])
    conn.executemany("INSERT INTO correspondence_groups VALUES(?,?,?,?,?)", [(rid, g, v[0], v[1], gdate[g]) for g, v in gm.items()])
    conn.execute("UPDATE daily_activity SET candidate_pairs=0,candidate_groups=0 WHERE scope=? AND region_id=? AND date BETWEEN ? AND ?",
                 (scope, region_id, start, end))
    per_day = defaultdict(lambda: [0, 0])
    for p in res["pairs"]:
        per_day[idx[p["viirs_id"]]["ts"][:10]][0] += 1
    for g, d in gdate.items():
        per_day[d][1] += 1
    for d, (np_, ng) in per_day.items():
        conn.execute("UPDATE daily_activity SET candidate_pairs=?,candidate_groups=? WHERE scope=? AND region_id=? AND date=?",
                     (np_, ng, scope, region_id, d))
    conn.commit()
    cap = 4000
    pairs = [{**p, "m": [idx[p["modis_id"]]["lat"], idx[p["modis_id"]]["lon"]], "v": [idx[p["viirs_id"]]["lat"], idx[p["viirs_id"]]["lon"]]}
             for p in res["pairs"][:cap]]
    keep = ("id", "sensor", "satellite", "ts", "lat", "lon", "frp", "confidence_raw", "confidence_class", "grid", "group_id", "status", "flags")
    return {"run_id": rid, "params": res["params"], "summary": res["summary"], "daily": H.daily_summary(res["observations"]),
            "observations": [{k: o[k] for k in keep} for o in res["observations"][:cap * 2]], "pairs": pairs,
            "truncated": len(res["observations"]) > cap * 2 or len(res["pairs"]) > cap}
