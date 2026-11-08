"""SYNTHETIC demonstration observations. Never NASA data. Stored with origin='demo' and labelled everywhere."""
import math
import random
from datetime import date, timedelta

import importer
import db

LAMBDA = [2, 2, 3, 5, 8, 3, 1, 1, 2, 25, 60, 10]  # synthetic mean daily VIIRS detections by month


def _pois(rnd, lam):
    if lam > 30:
        return max(0, int(round(rnd.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rnd.random()
        if p <= L:
            return k
        k += 1


def generate(years=range(2019, 2025), scale=1.0, seed=42):
    rnd, out = random.Random(seed), []
    for y in years:
        yf = rnd.uniform(0.7, 1.3)
        for d in (date(y, 1, 1) + timedelta(n) for n in range(366 if y % 4 == 0 else 365)):
            lam = LAMBDA[d.month - 1] * yf * scale * (3.5 if (y == 2022 and d.month == 11) else 1)
            sats = [("N", "0800")] + ([("N20", "0750")] if y >= 2019 else []) + ([("N21", "0745")] if y >= 2024 else [])
            for _ in range(_pois(rnd, lam)):
                lat, lon = rnd.uniform(29.5, 31.8), rnd.uniform(74.0, 76.5)
                sat, t = rnd.choice(sats)
                base = {"latitude": lat, "longitude": lon, "acq_date": d.isoformat(), "acq_time": t, "frp": round(rnd.uniform(1, 40), 1),
                        "daynight": "D", "instrument": "VIIRS", "satellite": sat, "confidence": rnd.choice("lnh"), "bright_ti4": 335, "version": "demo"}
                out.append(base)
                if rnd.random() < 0.45:
                    out.append({**base, "latitude": lat + rnd.gauss(0, .004), "longitude": lon + rnd.gauss(0, .004), "instrument": "MODIS",
                                "satellite": rnd.choice("TA"), "acq_time": rnd.choice(["0500", "0800"]), "confidence": rnd.randint(10, 100),
                                "brightness": 320, "frp": round(rnd.uniform(2, 60), 1)})
    return out


def load(years=range(2019, 2025), scale=1.0):
    conn = db.connect()
    iid = importer.create_import(conn, "SYNTHETIC demonstration dataset", "demo", "synthetic", "MODIS,VIIRS")
    conn.close()
    recs = generate(years, scale)
    conn = db.connect()
    conn.execute("UPDATE data_imports SET rows_total=? WHERE id=?", (len(recs), iid))
    conn.commit()
    conn.close()
    y0, y1 = min(years), max(years)
    importer.import_file("synthetic.json", __import__("json").dumps(recs).encode(), "demo", None, f"{y0}-01-01", f"{y1}-12-31", iid,
                         list(db.STUDY_BBOX), "Punjab + Haryana study area (synthetic)")
    return iid
