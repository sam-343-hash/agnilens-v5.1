"""Stubble Watch Delhi - backend.
Live data: NASA FIRMS (VIIRS fires) + Open-Meteo (wind forecast, PM2.5).
If an API fails (or no FIRMS key), falls back to demo data and says so in the UI.
"""
import csv, io, math, os, random, time
from datetime import datetime, timedelta, timezone


def _load_local_env():
    """Load simple KEY=VALUE entries from the project-local .env without overriding shell values."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                if key and key.replace("_", "").isalnum() and key not in os.environ:
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    os.environ[key] = value
    except FileNotFoundError:
        pass
    # Flask's optional auto-loader is disabled because the stdlib loader above
    # already handled .env and keeps this project dependency-free.
    os.environ.setdefault("FLASK_SKIP_DOTENV", "1")


_load_local_env()
import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import NotFound

import logging
from api import bp
import db
import importer as fire_importer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.register_blueprint(bp)
db.init()
DELHI = (28.6139, 77.2090)
BBOX = (73.8, 28.4, 77.3, 32.5)  # west,south,east,north = Punjab + Haryana belt
KEY = os.getenv("FIRMS_MAP_KEY", "")
_cache = {}


def cached(key, ttl, fn):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1], True, _cache[key][0]
    val = fn()
    _cache[key] = (now, val)
    return val, False, now


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def safe_firms_error(error):
    """Requests exceptions include the request URL; never return a MAP_KEY to clients."""
    message = str(error)
    key = os.getenv("FIRMS_MAP_KEY", "")
    return message.replace(key, "[redacted]")[:160] if key else message[:160]


SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]


def fetch_source(src, days=1):
    w, s, e, n = BBOX
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{KEY}/{src}/{w},{s},{e},{n}/{days}"
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    return r.text


def get_fires():
    """Return observations, demo flag and per-source status; failed sources never become implicit zeroes."""
    def live():
        if not KEY:
            raise RuntimeError("no FIRMS key")
        seen, out, results = set(), [], []
        for src in SOURCES:
            try:
                text = fetch_source(src)
                fire_importer.validate_firms_csv(text)
            except Exception as ex:
                results.append({"source": src, "status": "error", "error": safe_firms_error(ex)})
                continue
            results.append({"source": src, "status": "ok"})
            for row in csv.DictReader(io.StringIO(text)):
                if (row.get("confidence") or "n").lower() == "l":
                    continue
                k = (src, row["latitude"], row["longitude"], row.get("acq_date"), row.get("acq_time"))
                if k in seen:
                    continue
                seen.add(k)
                out.append({"lat": float(row["latitude"]), "lon": float(row["longitude"]),
                            "frp": float(row.get("frp") or 0), "date": row.get("acq_date", "")})
        return {"fires": out, "sources": results}
    try:
        result, was_cached, fetched_at = cached("fires", 600, live)
        return result["fires"], False, result["sources"], was_cached, datetime.fromtimestamp(fetched_at, timezone.utc).isoformat()
    except Exception as ex:
        rnd = random.Random(7)
        demo = [{"lat": rnd.gauss(30.6, 0.6), "lon": rnd.gauss(75.5, 0.8), "frp": rnd.uniform(2, 40), "date": "demo"}
                for _ in range(900)]
        return demo, True, [{"source": src, "status": "error", "error": safe_firms_error(ex)} for src in SOURCES], False, None


def get_weather():
    """Hourly wind (speed km/h, direction it blows FROM) and PM2.5 for next 48h."""
    def live():
        lat, lon = DELHI
        w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
            "latitude": lat, "longitude": lon, "hourly": "wind_speed_10m,wind_direction_10m",
            "forecast_days": 3, "timezone": "Asia/Kolkata"}).json()["hourly"]
        a = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality", timeout=20, params={
            "latitude": lat, "longitude": lon, "hourly": "pm2_5", "past_days": 1,
            "forecast_days": 3, "timezone": "Asia/Kolkata"}).json()["hourly"]
        pm = dict(zip(a["time"], a["pm2_5"]))
        return [{"t": t, "speed": s, "dir": d, "pm25": pm.get(t)}
                for t, s, d, in zip(w["time"], w["wind_speed_10m"], w["wind_direction_10m"])]
    try:
        rows, was_cached, fetched_at = cached("wx", 1800, live)
        return rows, False, was_cached, datetime.fromtimestamp(fetched_at, timezone.utc).isoformat()
    except Exception:
        base = time.time()
        rows = []
        for i in range(48):
            t = time.strftime("%Y-%m-%dT%H:00", time.localtime(base + i * 3600))
            rows.append({"t": t, "speed": 6 + 5 * math.sin(i / 7), "dir": 310 + 40 * math.sin(i / 10),
                         "pm25": 220 + 90 * math.sin(i / 9)})
        return rows, True, False, None


def risk(fires, speed, wind_from):
    """0-100 score: fires weighted by closeness, wind alignment and intensity.
    Heuristic - calibrate against historical PM2.5 for your pitch."""
    raw = 0.0
    for f in fires:
        d = haversine(DELHI, (f["lat"], f["lon"]))
        diff = abs((bearing(DELHI, (f["lat"], f["lon"])) - wind_from + 180) % 360 - 180)
        align = max(0.0, math.cos(math.radians(diff)))
        raw += align * math.exp(-d / 250) * (1 + min(f["frp"], 50) / 50)
    raw *= 1.6 / (1 + speed / 10)  # strong wind disperses smoke
    return round(100 * (1 - math.exp(-raw / 250)))


def level(score):
    if score < 35:
        return "Low", "Normal activity is fine."
    if score < 65:
        return "Moderate", "Sensitive groups (children, elderly, asthma) should limit time outdoors."
    return "High", "Wear an N95 outdoors, keep windows closed, run air purifiers, skip outdoor exercise."


@app.route("/api/status")
def status():
    fires, fdemo, source_status, fires_cached, fires_retrieved_at = get_fires()
    wx, wdemo, weather_cached, weather_retrieved_at = get_weather()
    now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:00")
    wx = [h for h in wx if h["t"] >= now_ist][:48] or wx[:48]
    hours = []
    for h in wx:
        s = risk(fires, h["speed"] or 0, h["dir"] or 0)
        hours.append({**h, "risk": s})
    now = hours[0]
    name, advice = level(now["risk"])
    peak = max(hours, key=lambda h: h["risk"])
    return jsonify({
        "demo": fdemo or wdemo, "fire_count": len(fires), "fire_data_mode": "synthetic" if fdemo else "live",
        "fire_sources": source_status, "fire_partial_failure": any(x["status"] == "error" for x in source_status),
        "fire_retrieved_at": fires_retrieved_at, "fire_cached": fires_cached,
        "weather_retrieved_at": weather_retrieved_at, "weather_cached": weather_cached,
        "fires": [{"lat": f["lat"], "lon": f["lon"], "frp": f["frp"]} for f in fires[:1500]],
        "delhi": DELHI, "now": now, "level": name, "advice": advice,
        "peak": {"t": peak["t"], "risk": peak["risk"]}, "hours": hours})


@app.errorhandler(413)
def upload_too_large(_error):
    limit_mib = app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)
    limit = f"{limit_mib:g} MiB" if limit_mib >= 1 else f"{app.config['MAX_CONTENT_LENGTH']} bytes"
    return jsonify({"error": f"Upload exceeds the configured limit ({limit})."}), 413



PAGES = ["map", "harmonize", "calendar", "compare", "regional", "anomalies", "data", "reports", "experimental"]


@app.route("/")
def index():
    return app.send_static_file("overview.html")


@app.route("/<page>")
def page(page):
    """AgniLens pages by name; anything else is served as a static asset (shared.css, shared.js)."""
    if page in PAGES:
        return app.send_static_file(page + ".html")
    try:
        return app.send_static_file(page)
    except NotFound:
        return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    app.run(debug=os.getenv("AGNILENS_DEBUG") == "1", port=int(os.getenv("PORT", "5001")))
