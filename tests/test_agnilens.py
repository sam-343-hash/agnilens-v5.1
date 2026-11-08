import json, os, sys, tempfile, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
os.environ["AGNILENS_DB"] = os.path.join(_tmp, "boot.db")
os.environ.pop("AGNILENS_DEBUG", None)
import analytics, db, demo_data, importer  # noqa: E402
import app as flask_app  # noqa: E402

HDR_V = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
BB = list(db.STUDY_BBOX)  # declared extent used by tests that need regional coverage
HDR_M = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"


def viirs(lat, lon, date, time="0800", sat="N", conf="n", frp="5.0"):
    return f"{lat},{lon},340,0.4,0.4,{date},{time},{sat},VIIRS,{conf},2.0NRT,300,{frp},D\n"


def modis(lat, lon, date, time="0805", sat="A", conf="80", frp="9.0"):
    return f"{lat},{lon},320,1.0,1.0,{date},{time},{sat},MODIS,{conf},6.1NRT,300,{frp},D\n"


class Base(unittest.TestCase):
    def setUp(self):
        db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
        db.init()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()

    def rows(self, sql="SELECT * FROM satellite_observations ORDER BY id"):
        return [dict(r) for r in self.conn.execute(sql)]

    def imp(self, text, name="a.csv", **kw):
        iid = importer.import_file(name, text.encode(), **kw)
        return dict(self.conn.execute("SELECT * FROM data_imports WHERE id=?", (iid,)).fetchone())


class TestImport(Base):
    def test_csv_multi_platform_and_sensor_detection(self):
        im = self.imp(HDR_V + viirs(30, 75, "2024-11-05") + viirs(30.1, 75, "2024-11-05", sat="N20") + viirs(30.2, 75, "2024-11-05", sat="N21"))
        self.assertEqual((im["status"], im["rows_imported"]), ("done", 3))
        self.assertEqual({r["satellite"] for r in self.rows()}, {"Suomi NPP", "NOAA-20", "NOAA-21"})
        im = self.imp(HDR_M + modis(31, 75, "2024-11-05", sat="T") + modis(31.1, 75, "2024-11-05", sat="A"), "m.csv")
        self.assertEqual({r["sensor"] for r in self.rows("SELECT sensor FROM satellite_observations")}, {"VIIRS", "MODIS"})
        self.assertEqual({r["satellite"] for r in self.rows() if r["sensor"] == "MODIS"}, {"Terra", "Aqua"})

    def test_invalid_records_rejected_with_reasons(self):
        txt = HDR_V + viirs(95, 75, "2024-11-05") + viirs("x", 75, "2024-11-05") + viirs(30, 75, "notadate") + viirs(30, 75, "2024-11-05", frp="-3") + viirs(30.5, 75, "2024-11-05")
        im = self.imp(txt)
        self.assertEqual(im["rows_imported"], 1)
        self.assertEqual(json.loads(im["reject_summary"]), {"invalid_coordinates": 2, "invalid_timestamp": 1, "negative_frp": 1})
        self.assertEqual(im["rows_rejected"], 4)

    def test_utc_timestamp_normalisation_and_raw_metadata(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05", time="530", conf="h"))
        r = self.rows()[0]
        self.assertEqual((r["acq_time"], r["acq_utc"], r["acq_date"]), ("0530", "2024-11-05T05:30:00Z", "2024-11-05"))
        self.assertEqual((r["confidence_raw"], r["version"], r["product"]), ("h", "2.0NRT", "VIIRS"))

    def test_unrecognised_satellite_kept_and_flagged(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05", sat="ZZ"))
        r = self.rows()[0]
        self.assertEqual(r["satellite"], "ZZ")
        self.assertIn("unrecognised_satellite", r["flags"])

    def test_exact_duplicates_skipped_but_nearby_points_kept(self):
        txt = HDR_V + viirs(30.0000, 75.0000, "2024-11-05") + viirs(30.0001, 75.0000, "2024-11-05")
        self.imp(txt)
        im2 = self.imp(txt, "again.csv")
        self.assertEqual(len(self.rows()), 2)  # nearby distinct detections both preserved
        self.assertEqual((im2["rows_imported"], im2["rows_duplicate"]), (0, 2))

    def test_json_and_geojson(self):
        rec = {"latitude": 30, "longitude": 75, "acq_date": "2024-11-05", "acq_time": "0800", "satellite": "N", "instrument": "VIIRS", "frp": 4}
        self.imp(json.dumps([rec]), "a.json")
        gj = {"features": [{"properties": {k: v for k, v in rec.items() if k not in ("latitude", "longitude")} | {"acq_time": "0900"},
                            "geometry": {"coordinates": [75.5, 30.5]}}]}
        self.imp(json.dumps(gj), "b.geojson")
        self.assertEqual(len(self.rows()), 2)

    def test_shapefile_rejected_with_clear_error(self):
        im = self.imp("x", "a.shp")
        self.assertEqual(im["status"], "error")
        self.assertIn("Shapefile", im["error"])

    def test_persistence_and_idempotent_migration(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05"))
        db.init()
        c2 = db.connect()
        self.assertEqual(c2.execute("SELECT COUNT(*) FROM satellite_observations").fetchone()[0], 1)
        self.assertEqual(c2.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))
        c2.close()

    def test_provenance_and_scope_separation(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05"))
        demo_data.load(range(2024, 2025), scale=0.05)
        origins = {r["origin"] for r in self.rows("SELECT DISTINCT origin FROM satellite_observations")}
        self.assertEqual(origins, {"nasa_archive", "demo"})
        c = flask_app.app.test_client()
        nasa = c.get("/api/overview?scope=nasa").get_json()
        demo = c.get("/api/overview?scope=demo").get_json()
        self.assertEqual(nasa["total"], 1)
        self.assertTrue(all(r["origin"] == "demo" for r in demo["by_source"]))


class TestCalendar(Base):
    def test_zero_vs_no_data_and_monthly(self):
        txt = HDR_V + viirs(30, 75, "2024-11-03") + viirs(30.1, 75, "2024-11-03") + viirs(30.2, 75, "2024-11-10")
        self.imp(txt, cov_start="2024-11-01", cov_end="2024-11-30", bbox=BB)
        cal = {d["date"]: d for d in analytics.calendar_view(self.conn, "nasa", "in-pb-hr", 2024)["days"]}
        self.assertEqual(cal["2024-11-03"]["viirs"]["count"], 2)
        self.assertEqual(cal["2024-11-04"]["viirs"]["status"], "confirmed_zero")      # covered, genuinely zero
        self.assertEqual(cal["2024-10-31"]["viirs"]["status"], "no_data")   # outside coverage
        self.assertEqual(cal["2024-11-04"]["modis"]["status"], "no_data")   # MODIS never imported
        self.assertIsNone(cal["2024-10-31"]["value"])
        m = {x["month"]: x for x in analytics.monthly_view(self.conn, "nasa", "in-pb-hr", [2024])}
        self.assertEqual(m["2024-11"]["viirs"]["count"], 3)
        self.assertEqual(m["2024-11"]["viirs"]["coverage"], 1.0)
        self.assertIsNone(m["2024-10"]["viirs"]["count"])

    def test_assumed_coverage_is_flagged(self):
        im = self.imp(HDR_V + viirs(30, 75, "2024-11-03") + viirs(30, 75, "2024-11-05"))
        self.assertEqual((im["coverage_assumed"], im["coverage_start"], im["coverage_end"]), (1, "2024-11-03", "2024-11-05"))


class TestAnomaly(unittest.TestCase):
    def series(self, counts, mm="11"):
        return [{"month": f"{y}-{mm}", "count": c, "coverage": 1.0} for y, c in counts.items()]

    def test_spike_flagged_with_robust_score(self):
        s = self.series({2019: 100, 2020: 110, 2021: 95, 2022: 105, 2023: 100, 2024: 400})
        r = {i["month"]: i for i in analytics.monthly_anomalies(s)}
        self.assertTrue(r["2024-11"]["flagged"])
        self.assertEqual(r["2024-11"]["direction"], "above")
        self.assertFalse(r["2021-11"]["flagged"])

    def test_insufficient_baseline_not_scored(self):
        r = analytics.monthly_anomalies(self.series({2023: 100, 2024: 400}))
        self.assertTrue(all(i["status"] == "insufficient_baseline" and not i["flagged"] for i in r))

    def test_low_coverage_months_excluded(self):
        s = self.series({2019: 100, 2020: 100, 2021: 100, 2022: 100})
        s[0]["coverage"] = 0.5
        self.assertNotIn("2019-11", [i["month"] for i in analytics.monthly_anomalies(s)])

    def test_constant_baseline_uses_noise_floor(self):
        sc = analytics.score(5, [5, 5, 5, 5])      # MAD = 0: scale falls back to sqrt(median)
        self.assertEqual(sc["robust_z"], 0.0)
        self.assertFalse(analytics.is_flagged(sc)[0])
        self.assertTrue(analytics.is_flagged(analytics.score(50, [10, 10, 10, 10, 12]))[0])

    def test_small_count_noise_not_flagged(self):
        self.assertFalse(analytics.is_flagged(analytics.score(14, [10, 10, 11, 9, 10]))[0])

    def test_platform_change_caveat(self):
        s = self.series({2019: 100, 2020: 100, 2021: 101, 2022: 99, 2023: 100, 2024: 300})
        plat = {f"{y}-11": {"Suomi NPP": 50} for y in range(2019, 2024)} | {"2024-11": {"Suomi NPP": 50, "NOAA-21": 40}}
        r = {i["month"]: i for i in analytics.monthly_anomalies(s, platforms=plat)}
        self.assertIn("caveat", r["2024-11"])

    def test_moving_average(self):
        self.assertEqual(analytics.moving_average([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_daily_anomaly(self):
        daily = {}
        for y in range(2019, 2024):
            for d in range(1, 29):
                daily[f"{y}-11-{d:02d}"] = 10 + (d % 3)
        daily["2024-11-10"] = 200
        r = {i["date"]: i for i in analytics.daily_anomalies(daily)}
        self.assertTrue(r["2024-11-10"]["flagged"])


class TestHarmonizeDB(Base):
    def test_matches_persisted_and_calendar_updated(self):
        self.imp(HDR_V + viirs(30.0, 75.0, "2024-11-05"))
        self.imp(HDR_M + modis(30.003, 75.0, "2024-11-05", time="0805"), "m.csv")
        r = analytics.run_harmonization(self.conn, "nasa", "in-pb-hr", "2024-11-01", "2024-11-30", 1000, 120)
        self.assertEqual((r["summary"]["candidate_pairs"], r["summary"]["groups"]), (1, 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM harmonization_matches").fetchone()[0], 1)
        d = self.conn.execute("SELECT candidate_groups FROM daily_activity WHERE date='2024-11-05' AND region_id='in-pb-hr'").fetchone()
        self.assertEqual(d[0], 1)

    def test_too_large_range_refused(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05") + viirs(30.1, 75, "2024-11-05"))
        with self.assertRaises(analytics.TooLarge):
            analytics.run_harmonization(self.conn, "nasa", "in-pb-hr", "2024-11-01", "2024-11-30", 1000, 120, max_rows=1)


class TestNRT(Base):
    def test_failed_source_is_not_zero_and_key_not_leaked(self):
        def fake(key, src, bbox, days):
            if src == "VIIRS_NOAA21_NRT":
                raise RuntimeError(f"401 for url https://x/{key}/{src}")
            if src == "MODIS_NRT":
                return HDR_M  # header only = genuinely zero detections
            return HDR_V + viirs(30, 75, "2024-11-05")
        res = importer.ingest_nrt("SECRETKEY", 3, fetch=fake)
        by = {r["source"]: r for r in res}
        self.assertEqual(by["VIIRS_NOAA21_NRT"]["status"], "error")
        self.assertNotIn("SECRETKEY", json.dumps(res))
        self.assertEqual((by["MODIS_NRT"]["status"], by["MODIS_NRT"]["rows"]), ("ok", 0))
        errs = self.rows("SELECT * FROM data_imports WHERE status='error'")
        self.assertEqual(len(errs), 1)
        self.assertNotIn("SECRETKEY", errs[0]["error"])
        self.assertIsNone(errs[0]["coverage_start"])

    def test_error_text_response_is_a_failure(self):
        res = importer.ingest_nrt("K", 1, fetch=lambda *a: "Invalid MAP_KEY.")
        self.assertTrue(all(r["status"] == "error" for r in res))

    def test_nrt_coverage_counts_only_full_days(self):
        from datetime import datetime, timezone
        n = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(importer.nrt_coverage(1, n), (None, None))
        self.assertEqual(importer.nrt_coverage(3, n), ("2026-11-05", "2026-11-06"))


class TestAPI(Base):
    def setUp(self):
        super().setUp()
        self.c = flask_app.app.test_client()

    def test_basic_endpoints_and_validation(self):
        self.assertEqual(self.c.get("/api/health").get_json()["status"], "ok")
        self.assertEqual(len(self.c.get("/api/regions").get_json()), 4)
        self.assertEqual(self.c.get("/api/calendar?scope=bad").status_code, 400)
        self.assertEqual(self.c.get("/api/calendar?region=nowhere").status_code, 404)
        self.assertEqual(self.c.post("/api/harmonize?scope=nasa").status_code, 400)
        self.assertEqual(self.c.get("/api/anomalies?sensor=XXX").status_code, 400)
        for p in ("/", "/map", "/harmonize", "/calendar", "/compare", "/regional", "/anomalies", "/data", "/reports", "/experimental"):
            self.assertEqual(self.c.get(p).status_code, 200, p)

    def test_every_local_asset_referenced_by_a_page_is_served(self):
        """Regression: a catch-all page route once returned 404 for /shared.css and /shared.js, leaving every page unstyled."""
        import glob, re
        seen = set()
        for f in glob.glob(os.path.join(ROOT, "static", "*.html")):
            html = open(f).read()
            seen |= set(re.findall(r'(?:href|src)="(/[^"#?]+\.(?:css|js))"', html))
        self.assertIn("/shared.css", seen)
        self.assertIn("/shared.js", seen)
        for url in sorted(seen):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn(("css" if url.endswith(".css") else "javascript"), r.content_type, url)
        self.assertEqual(self.c.get("/definitely-missing.js").status_code, 404)
        self.assertEqual(self.c.get("/../app.py").status_code, 404)

    def test_debug_hidden_and_key_not_exposed(self):
        self.assertEqual(self.c.get("/api/debug").status_code, 404)
        os.environ["FIRMS_MAP_KEY"] = "TOPSECRET"
        try:
            self.assertNotIn("TOPSECRET", self.c.get("/api/health").get_data(as_text=True))
        finally:
            os.environ.pop("FIRMS_MAP_KEY")

    def test_nrt_refresh_without_key(self):
        self.assertEqual(self.c.post("/api/nrt/refresh").status_code, 400)

    def test_upload_then_query_and_export(self):
        import io
        data = (HDR_V + viirs(30, 75, "2024-11-05") + viirs(30.2, 75, "2024-11-06")).encode()
        r = self.c.post("/api/import", data={"file": (io.BytesIO(data), "x.csv"), "coverage_start": "2024-11-01", "coverage_end": "2024-11-30", "extent": "in-pb-hr"},
                        content_type="multipart/form-data")
        self.assertEqual(r.status_code, 202)
        iid = r.get_json()["import_id"]
        for _ in range(50):
            st = self.c.get(f"/api/imports/{iid}").get_json()
            if st["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual((st["status"], st["rows_imported"], st["origin"]), ("done", 2, "nasa_archive"))
        m = self.c.get("/api/map/observations?start=2024-11-01&end=2024-11-30").get_json()
        self.assertEqual((m["total_matching"], m["returned"]), (2, 2))
        csv_ = self.c.get("/api/reports/export?start=2024-11-04&end=2024-11-06&format=csv").get_data(as_text=True)
        self.assertIn("NASA FIRMS data", csv_)
        self.assertIn("2024-11-05,no_data,,,,active,1", csv_)
        self.assertIn("AgniLens regional report", self.c.get("/api/reports/export?start=2024-11-01&end=2024-11-30&format=html").get_data(as_text=True))

    def test_demo_is_labelled_and_removable(self):
        r = self.c.post("/api/demo/load").get_json()
        self.assertIn("SYNTHETIC", r["label"])
        csv_ = self.c.get("/api/reports/export?scope=demo&start=2024-10-01&end=2024-10-05").get_data(as_text=True)
        self.assertIn("SYNTHETIC DEMONSTRATION", csv_)
        self.c.delete("/api/demo")
        self.assertEqual(self.c.get("/api/overview?scope=demo").get_json()["total"], 0)

    def test_demo_anomalies_end_to_end(self):
        demo_data.load(range(2019, 2025), scale=0.3)
        a = self.c.get("/api/anomalies?scope=demo&sensor=VIIRS&level=monthly").get_json()
        self.assertEqual(a["status"], "ok")
        self.assertIn("2022-11", [x["month"] for x in a["anomalies"]])  # synthetic 3.5x November 2022 burst
        none = self.c.get("/api/anomalies?scope=nasa&sensor=VIIRS").get_json()
        self.assertEqual(none["status"], "no_coverage")


if __name__ == "__main__":
    unittest.main(verbosity=2)
