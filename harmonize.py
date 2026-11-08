"""MODIS / VIIRS hot-spot harmonization.

Produces CANDIDATE correspondences between sensors. A match means "close in space
and time", not "verified to be the same physical fire". Raw rows are never modified.
"""
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone

CELL_DEG = 0.01  # ~1.1 km grid for spatial indexing / grid ids


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _ts(date, time):
    t = str(time).strip().zfill(4)
    return datetime.strptime(f"{date} {t[:2]}:{t[2:]}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def _conf_class(sensor, raw):
    """Coarse label only. MODIS (0-100) and VIIRS (l/n/h) confidences are NOT equivalent."""
    if sensor == "MODIS":
        v = _f(raw)
        return None if v is None else "low" if v < 30 else "nominal" if v < 80 else "high"
    return {"l": "low", "n": "nominal", "h": "high"}.get(str(raw).strip().lower())


def cell_id(lat, lon):
    return f"{math.floor(lat / CELL_DEG)}_{math.floor(lon / CELL_DEG)}"


def normalize(rows, sensor):
    """Raw FIRMS dict rows -> (clean observations, rejected-reason counts)."""
    clean, rej, seen = [], defaultdict(int), set()
    for i, r in enumerate(rows):
        lat, lon = _f(r.get("latitude")), _f(r.get("longitude"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            rej["invalid_coordinates"] += 1
            continue
        try:
            ts = _ts(r["acq_date"], r["acq_time"])
        except (KeyError, ValueError):
            rej["invalid_timestamp"] += 1
            continue
        key = (r.get("satellite"), lat, lon, ts)  # full source precision, never rounded
        if key in seen:
            rej["duplicate"] += 1
            continue
        seen.add(key)
        frp = _f(r.get("frp"))
        bright = _f(r.get("brightness") if sensor == "MODIS" else r.get("bright_ti4"))
        flags = [f for f, bad in (("missing_frp", frp is None), ("missing_brightness", bright is None)) if bad]
        clean.append({"id": f"{sensor}:{i}", "sensor": sensor, "satellite": r.get("satellite", ""),
                      "ts": ts, "lat": lat, "lon": lon, "frp": frp, "brightness_k": bright,
                      "confidence_raw": r.get("confidence"), "confidence_class": _conf_class(sensor, r.get("confidence")),
                      "daynight": r.get("daynight"), "grid": cell_id(lat, lon), "flags": flags})
    return clean, dict(rej)


def match(modis, viirs, max_dist_m=1000.0, max_dt_min=120.0):
    """Many-to-many candidate pairs, then connected components -> correspondence groups."""
    cells = defaultdict(list)
    for m in modis:
        cells[(math.floor(m["lat"] / CELL_DEG), math.floor(m["lon"] / CELL_DEG))].append(m)
    pairs = []
    for v in viirs:
        ci, cj = math.floor(v["lat"] / CELL_DEG), math.floor(v["lon"] / CELL_DEG)
        ri = math.ceil(max_dist_m / (111000 * CELL_DEG))
        rj = math.ceil(max_dist_m / (111000 * CELL_DEG * max(math.cos(math.radians(v["lat"])), 0.2)))
        for di in range(-ri, ri + 1):
            for dj in range(-rj, rj + 1):
                for m in cells.get((ci + di, cj + dj), ()):
                    d = haversine_m(v["lat"], v["lon"], m["lat"], m["lon"])
                    dt = abs((v["ts"] - m["ts"]).total_seconds()) / 60
                    if d <= max_dist_m and dt <= max_dt_min:
                        distance_fraction = d / max_dist_m if max_dist_m else (0.0 if d == 0 else 1.0)
                        time_fraction = dt / max_dt_min if max_dt_min else (0.0 if dt == 0 else 1.0)
                        pairs.append({"modis_id": m["id"], "viirs_id": v["id"], "distance_m": round(d, 1),
                                      "dt_min": round(dt, 1), "distance_threshold_fraction": round(distance_fraction, 4),
                                      "time_threshold_fraction": round(time_fraction, 4), "status": "candidate",
                                      "quality_note": "Fractions show proximity to this run's configured cutoffs; they are not probabilities."})
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        parent[find(p["modis_id"])] = find(p["viirs_id"])
    gid, members = {}, defaultdict(list)
    for o in modis + viirs:
        if o["id"] in parent:
            members[find(o["id"])].append(o["id"])
    for n, root in enumerate(sorted(members), 1):
        for oid in members[root]:
            gid[oid] = f"G{n:05d}"
    obs = []
    for o in modis + viirs:
        g = gid.get(o["id"])
        obs.append({**o, "ts": o["ts"].isoformat(), "group_id": g,
                    "status": "candidate_match" if g else f"{o['sensor'].lower()}_only"})
    groups = defaultdict(lambda: {"modis": 0, "viirs": 0})
    for o in obs:
        if o["group_id"]:
            groups[o["group_id"]]["modis" if o["sensor"] == "MODIS" else "viirs"] += 1
    nm = sum(1 for o in obs if o["sensor"] == "MODIS" and o["group_id"])
    nv = sum(1 for o in obs if o["sensor"] == "VIIRS" and o["group_id"])
    return {"params": {"max_dist_m": max_dist_m, "max_dt_min": max_dt_min, "grid_deg": CELL_DEG},
            "observations": obs, "pairs": pairs,
            "summary": {"modis_raw": len(modis), "viirs_raw": len(viirs), "candidate_pairs": len(pairs),
                        "groups": len(groups), "modis_matched": nm, "viirs_matched": nv,
                        "modis_only": len(modis) - nm, "viirs_only": len(viirs) - nv,
                        "many_to_one_groups": sum(1 for g in groups.values() if g["modis"] > 1 or g["viirs"] > 1),
                        "median_distance_m": round(statistics.median([p["distance_m"] for p in pairs]), 1) if pairs else None,
                        "median_dt_min": round(statistics.median([p["dt_min"] for p in pairs]), 1) if pairs else None}}


def daily_summary(obs):
    """Per-date, per-sensor counts and FRP (FRP is summarised per sensor, never merged)."""
    d = defaultdict(lambda: defaultdict(list))
    for o in obs:
        d[o["ts"][:10]][o["sensor"]].append(o["frp"])
    out = []
    for day in sorted(d):
        row = {"date": day}
        for s in ("MODIS", "VIIRS"):
            vals = d[day].get(s, [])
            f = [x for x in vals if x is not None]
            row[s.lower()] = {"count": len(vals), "frp_mean": round(statistics.mean(f), 2) if f else None,
                              "frp_max": max(f) if f else None}
        out.append(row)
    return out
