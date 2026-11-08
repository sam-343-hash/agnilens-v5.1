"""V5.1 integrity tests: geographic coverage, provenance, coverage states, platform sets, migration."""
import io, json, os, sqlite3, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_agnilens import BB, HDR_M, HDR_V, Base, modis, viirs  # noqa: E402  (also sets AGNILENS_DB before app import)
import analytics, db, demo_data, importer  # noqa: E402
import app as flask_app  # noqa: E402
from validate_archive_pair import experiment  # noqa: E402

HARYANA = [74.46, 27.65, 77.60, 30.93]


def cal(conn, region, year=2024, scope="nasa", metric="viirs"):
    return {d["date"]: d for d in analytics.calendar_view(conn, scope, region, year, metric)["days"]}


class TestExtent(Base):
    def extent(self, rid):
        return importer.resolve_extent(self.conn, rid)

    def test_haryana_extent_covers_haryana_not_punjab(self):
        bb, lab = self.extent("in-haryana")
        self.imp(HDR_V + viirs(28.5, 76.0, "2024-11-03"), bbox=bb, extent_label=lab, cov_start="2024-11-01", cov_end="2024-11-30")
        self.assertEqual(cal(self.conn, "in-haryana")["2024-11-04"]["viirs"]["status"], "confirmed_zero")
        self.assertEqual(cal(self.conn, "in-punjab")["2024-11-04"]["viirs"]["status"], "no_data")
        self.assertEqual(cal(self.conn, "in-pb-hr")["2024-11-04"]["viirs"]["status"], "no_data")  # study area is larger than Haryana

    def test_extent_is_declared_not_inferred_from_detections(self):
        bb, lab = self.extent("in-haryana")   # detections are in Punjab, but only Haryana is declared
        self.imp(HDR_V + viirs(31.0, 75.0, "2024-11-03"), bbox=bb, extent_label=lab, cov_start="2024-11-01", cov_end="2024-11-30")
        d = cal(self.conn, "in-punjab")
        self.assertEqual(d["2024-11-03"]["viirs"]["status"], "active")        # the detection itself is real
        self.assertEqual(d["2024-11-04"]["viirs"]["status"], "no_data")       # but coverage was never declared for Punjab

    def test_no_declared_extent_gives_no_regional_coverage(self):
        self.imp(HDR_V + viirs(30.0, 75.0, "2024-11-03"), cov_start="2024-11-01", cov_end="2024-11-30")
        for rid in ("in-punjab", "in-haryana", "in-pb-hr", "in-all"):
            self.assertEqual(cal(self.conn, rid)["2024-11-04"]["viirs"]["status"], "no_data", rid)

    def test_punjab_plus_haryana_extent_covers_both_parts(self):
        bb, lab = self.extent("in-pb-hr")
        self.imp(HDR_V + viirs(30.0, 75.0, "2024-11-03"), bbox=bb, extent_label=lab, cov_start="2024-11-01", cov_end="2024-11-30")
        for rid in ("in-punjab", "in-haryana", "in-pb-hr"):
            self.assertEqual(cal(self.conn, rid)["2024-11-04"]["viirs"]["status"], "confirmed_zero", rid)
        self.assertEqual(cal(self.conn, "in-all")["2024-11-04"]["viirs"]["status"], "no_data")

    def test_bbox_validation(self):
        for bad in (["a", 1, 2, 3], [10, 0, 5, 5], [0, 10, 5, 5], [-200, 0, 5, 5], [0, 0, 5, 95], [None] * 4, [0, 0, float("nan"), 5]):
            with self.assertRaises(ValueError, msg=str(bad)):
                db.validate_bbox(*bad)
        self.assertEqual(db.validate_bbox("74", "27", "77", "31"), [74.0, 27.0, 77.0, 31.0])

    def post(self, c, extra, name="x.csv"):
        data = {"file": (io.BytesIO((HDR_V + viirs(28.5, 76, "2024-11-05")).encode()), name)}
        data.update(extra)
        return c.post("/api/import", data=data, content_type="multipart/form-data")

    def wait(self, c, iid):
        for _ in range(60):
            st = c.get(f"/api/imports/{iid}").get_json()
            if st["status"] != "running":
                return st
            time.sleep(0.1)

    def test_api_requires_valid_extent_and_stores_it(self):
        c = flask_app.app.test_client()
        self.assertEqual(self.post(c, {}).status_code, 400)                                         # extent required
        self.assertEqual(self.post(c, {"extent": "mars"}).status_code, 400)
        self.assertEqual(self.post(c, {"extent": "custom", "west": "80", "south": "0", "east": "70", "north": "5"}).status_code, 400)
        self.assertEqual(self.post(c, {"extent": "in-haryana", "coverage_start": "2024-11-01"}).status_code, 400)  # one date only
        self.assertEqual(self.post(c, {"extent": "in-haryana", "coverage_start": "2024-12-01", "coverage_end": "2024-11-01"}).status_code, 400)
        r = self.post(c, {"extent": "in-haryana", "coverage_start": "2024-11-01", "coverage_end": "2024-11-30"})
        self.assertEqual(r.status_code, 202)
        st = self.wait(c, r.get_json()["import_id"])
        self.assertEqual(json.loads(st["bbox"]), HARYANA)
        self.assertIn("approximate", st["extent_label"])
        r = self.post(c, {"extent": "custom", "west": "74", "south": "28", "east": "76", "north": "30"}, "y.csv")
        st = self.wait(c, r.get_json()["import_id"])
        self.assertEqual(json.loads(st["bbox"]), [74.0, 28.0, 76.0, 30.0])
        self.assertIn("Custom box", st["extent_label"])

    def test_declare_extent_for_legacy_import_endpoint(self):
        iid = self.imp(HDR_V + viirs(30, 75, "2024-11-03"), cov_start="2024-11-01", cov_end="2024-11-30")["id"]
        self.assertEqual(cal(self.conn, "in-pb-hr")["2024-11-04"]["viirs"]["status"], "no_data")
        c = flask_app.app.test_client()
        self.assertEqual(c.post(f"/api/imports/{iid}/extent", json={"extent": "nope"}).status_code, 400)
        self.assertEqual(c.post("/api/imports/9999/extent", json={"extent": "in-pb-hr"}).status_code, 404)
        self.assertEqual(c.post(f"/api/imports/{iid}/extent", json={"extent": "in-pb-hr"}).status_code, 200)
        self.assertEqual(cal(self.conn, "in-pb-hr")["2024-11-04"]["viirs"]["status"], "confirmed_zero")

    def test_import_history_exposes_extent(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-03"), bbox=BB, extent_label="Punjab + Haryana (approximate box)")
        h = flask_app.app.test_client().get("/api/imports").get_json()[0]
        self.assertEqual(json.loads(h["bbox"]), BB)
        self.assertIn("approximate", h["extent_label"])


class TestProvenance(Base):
    ROW = viirs(30.0, 75.0, "2024-11-05")

    def test_identical_demo_and_nasa_observations_coexist(self):
        txt = (HDR_V + self.ROW).encode()
        importer.import_file("nasa.csv", txt, "nasa_archive", bbox=BB)
        importer.import_file("demo.csv", txt, "demo", bbox=BB)
        rows = self.rows("SELECT scope,origin FROM satellite_observations ORDER BY scope")
        self.assertEqual([(r["scope"], r["origin"]) for r in rows], [("demo", "demo"), ("nasa", "nasa_archive")])
        c = flask_app.app.test_client()
        self.assertEqual(c.get("/api/overview?scope=nasa").get_json()["total"], 1)
        self.assertEqual(c.get("/api/overview?scope=demo").get_json()["total"], 1)

    def test_archive_and_nrt_same_detection_not_double_counted(self):
        a = self.imp(HDR_V + self.ROW, "archive.csv", bbox=BB, cov_start="2024-11-01", cov_end="2024-11-30")

        def fake(key, src, bbox, days):
            return (HDR_V + self.ROW) if src == "VIIRS_SNPP_NRT" else (HDR_M if src == "MODIS_NRT" else HDR_V)
        importer.ingest_nrt("K", 3, fetch=fake)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM satellite_observations")[0]["n"], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM observation_sources")[0]["n"], 2)
        nrt = self.rows("SELECT * FROM data_imports WHERE source_name='VIIRS_SNPP_NRT'")[0]
        self.assertEqual((nrt["rows_imported"], nrt["rows_duplicate"]), (0, 1))     # known detection, not a new one
        o = flask_app.app.test_client().get("/api/overview?scope=nasa").get_json()
        self.assertEqual(o["totals"]["VIIRS"], 1)
        self.assertEqual(sum(p["links"] for p in o["provenance"]), 2)
        d = self.rows("SELECT viirs_count FROM daily_activity WHERE scope='nasa' AND region_id='in-pb-hr' AND date='2024-11-05'")
        self.assertEqual(d[0]["viirs_count"], 1)

    def test_both_source_references_remain_retrievable(self):
        self.imp(HDR_V + self.ROW, "archive.csv", bbox=BB)
        importer.ingest_nrt("K", 3, fetch=lambda k, s, b, d: (HDR_V + self.ROW) if s == "VIIRS_SNPP_NRT" else (HDR_M if s == "MODIS_NRT" else HDR_V))
        oid = self.rows("SELECT id FROM satellite_observations")[0]["id"]
        r = flask_app.app.test_client().get(f"/api/observations/{oid}/sources").get_json()
        self.assertEqual({s["origin"] for s in r["sources"]}, {"nasa_archive", "nasa_nrt"})
        self.assertEqual({s["source_ref"] for s in r["sources"]}, {"archive.csv", "VIIRS_SNPP_NRT"})
        self.assertTrue(all(s["import_id"] for s in r["sources"]))
        self.assertEqual(flask_app.app.test_client().get("/api/observations/99999/sources").status_code, 404)

    def test_different_nearby_coordinates_stay_distinct(self):
        self.imp(HDR_V + viirs(30.00001, 75.0, "2024-11-05") + viirs(30.00002, 75.0, "2024-11-05"))
        self.assertEqual(len(self.rows()), 2)

    def test_per_source_values_preserved_when_sources_disagree(self):
        self.imp(HDR_V + viirs(30, 75, "2024-11-05", conf="n"), "a.csv")
        self.imp(HDR_V + viirs(30, 75, "2024-11-05", conf="h"), "b.csv")
        src = self.rows("SELECT source_ref,confidence_raw FROM observation_sources ORDER BY import_id")
        self.assertEqual([(s["source_ref"], s["confidence_raw"]) for s in src], [("a.csv", "n"), ("b.csv", "h")])
        self.assertEqual(len(self.rows()), 1)

    def test_demo_clear_removes_only_demo_and_cascades_links(self):
        self.imp(HDR_V + self.ROW, "n.csv")
        demo_data.load(range(2024, 2025), scale=0.05)
        flask_app.app.test_client().delete("/api/demo")
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM satellite_observations")[0]["n"], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM observation_sources")[0]["n"], 1)

    def test_satellite_aliases_normalize_but_original_labels_survive(self):
        labels = {"SNPP": "Suomi NPP", "S-NPP": "Suomi NPP", "N20": "NOAA-20", "NOAA20": "NOAA-20",
                  "J1": "NOAA-20", "N21": "NOAA-21", "NOAA21": "NOAA-21", "J2": "NOAA-21"}
        for i, (label, canonical) in enumerate(labels.items()):
            row = viirs(30 + i * 0.01, 75, "2024-11-05").replace(",N,", f",{label},")
            self.imp(HDR_V + row, f"alias-{label}.csv")
            got = self.rows("SELECT satellite,platform_raw FROM satellite_observations ORDER BY id")[-1]
            self.assertEqual(got["satellite"], canonical)
            self.assertEqual(got["platform_raw"], label)
        source = self.rows("SELECT platform_raw FROM observation_sources ORDER BY import_id")
        self.assertEqual([r["platform_raw"] for r in source], list(labels))

    def test_firms_error_csv_is_rejected_as_source_failure(self):
        results = importer.ingest_nrt("K", 1, fetch=lambda *args: "ERROR: invalid MAP_KEY")
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r["status"] == "error" for r in results))

    def test_map_bbox_and_upload_extension_are_validated(self):
        c = flask_app.app.test_client()
        self.assertEqual(c.get("/api/map/observations?bbox=1,2,3").status_code, 400)
        resp = c.post("/api/import", data={"file": (io.BytesIO(b"x"), "payload.exe"), "extent": "in-pb-hr"},
                      content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)

    def test_reports_limit_source_counts_and_months_to_requested_region_period(self):
        data = HDR_V + viirs(30, 75, "2024-11-05") + viirs(30, 90, "2024-11-05") + viirs(30.2, 75.2, "2024-10-05")
        bbox, label = importer.resolve_extent(self.conn, "in-all")
        self.imp(data, "wide.csv", bbox=bbox, extent_label=label, cov_start="2024-10-01", cov_end="2024-11-30")
        client = flask_app.app.test_client()
        html_report = client.get("/api/reports/export?start=2024-11-01&end=2024-11-30&format=html").get_data(as_text=True)
        self.assertIn("<td>nasa_archive</td><td>VIIRS</td><td>Suomi NPP</td><td>1</td>", html_report)
        self.assertIn("<td>2024-11</td>", html_report)
        self.assertNotIn("<td>2024-10</td>", html_report)
        self.assertIn("wide.csv", html_report)
        csv_report = client.get("/api/reports/export?start=2024-11-01&end=2024-11-30&format=csv").get_data(as_text=True)
        self.assertIn("candidate_pairs,candidate_groups", csv_report)
        self.assertIn("started=", csv_report)

    def test_firms_request_error_redacts_map_key(self):
        previous = os.environ.get("FIRMS_MAP_KEY")
        os.environ["FIRMS_MAP_KEY"] = "test-map-key-secret"
        try:
            message = flask_app.safe_firms_error(RuntimeError("request failed: https://example.invalid/test-map-key-secret"))
        finally:
            if previous is None:
                os.environ.pop("FIRMS_MAP_KEY", None)
            else:
                os.environ["FIRMS_MAP_KEY"] = previous
        self.assertNotIn("test-map-key-secret", message)
        self.assertIn("[redacted]", message)


class TestArchiveExperiment(unittest.TestCase):
    def test_threshold_sensitivity_report_is_reproducible_and_caveated(self):
        with tempfile.TemporaryDirectory() as folder:
            modis_path, viirs_path = os.path.join(folder, "m.csv"), os.path.join(folder, "v.csv")
            with open(modis_path, "w") as f:
                f.write(HDR_M + modis(30, 75, "2024-11-05", time="0800"))
            with open(viirs_path, "w") as f:
                f.write(HDR_V + viirs(30.01, 75, "2024-11-05", time="0810"))
            result = experiment(modis_path, viirs_path, [74, 27, 77, 33], [(500, 30), (2000, 120)])
        self.assertIn("not scientific validation", result["interpretation"])
        self.assertEqual(result["files"]["modis"]["records_accepted"], 1)
        self.assertEqual([x["candidate_pairs"] for x in result["sensitivity"]], [0, 1])
        self.assertEqual(result["daily_detection_counts"][0]["modis"], 1)


class TestMigration(unittest.TestCase):
    def legacy_db(self):
        path = os.path.join(tempfile.mkdtemp(), "legacy.db")
        c = sqlite3.connect(path)
        c.executescript(db.MIGRATIONS[0])
        c.execute("PRAGMA user_version=1")
        c.execute("INSERT INTO data_imports(id,filename,origin,status,sensors,coverage_start,coverage_end,bbox) VALUES(1,'old.csv','nasa_archive','done','VIIRS','2024-11-01','2024-11-30',NULL)")
        c.execute("INSERT INTO data_imports(id,filename,origin,status) VALUES(2,'demo','demo','done')")
        ins = ("INSERT INTO satellite_observations(sensor,satellite,product,version,acq_date,acq_time,acq_utc,lat,lon,frp,confidence_raw,"
               "origin,source_ref,import_id,flags) VALUES('VIIRS','Suomi NPP','VIIRS','2.0NRT','2024-11-05','0800','2024-11-05T08:00:00Z',?,75.0,5.0,'n',?,'old.csv',?,'')")
        c.execute(ins, (30.0, "nasa_archive", 1))
        c.execute(ins, (31.0, "demo", 2))
        c.commit()
        c.close()
        return path

    def test_existing_database_upgrades_without_losing_data(self):
        db.DB_PATH = self.legacy_db()
        db.init()
        c = db.connect()
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))
        rows = {r["lat"]: r for r in c.execute("SELECT * FROM satellite_observations")}
        self.assertEqual((rows[30.0]["scope"], rows[31.0]["scope"]), ("nasa", "demo"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM observation_sources").fetchone()[0], 2)       # provenance backfilled
        self.assertIn("extent_label", [r[1] for r in c.execute("PRAGMA table_info(data_imports)")])
        self.assertIsNone(c.execute("SELECT bbox FROM data_imports WHERE id=1").fetchone()[0])           # legacy extent stays undeclared
        # the old collision is gone: the same identity can now exist in both scopes, but not twice in one scope
        ident = ("VIIRS", "Suomi NPP", "2024-11-05T08:00:00Z", 30.0, 75.0)
        ins = ("INSERT OR IGNORE INTO satellite_observations(scope,sensor,satellite,acq_date,acq_utc,lat,lon,origin) "
               "VALUES(?,?,?,'2024-11-05',?,?,?,?)")
        self.assertEqual(c.execute(ins, ("demo",) + ident[:3] + ident[3:] + ("demo",)).rowcount, 1)
        self.assertEqual(c.execute(ins, ("nasa",) + ident[:3] + ident[3:] + ("nasa_nrt",)).rowcount, 0)
        c.commit()
        c.close()
        db.init()   # idempotent
        c = db.connect()
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM satellite_observations").fetchone()[0], 3)
        c.close()

    def test_legacy_import_gives_no_coverage_until_extent_declared(self):
        db.DB_PATH = self.legacy_db()
        db.init()
        c = db.connect()
        analytics.rebuild_activity(c, "nasa")
        self.assertEqual(cal(c, "in-pb-hr")["2024-11-10"]["viirs"]["status"], "no_data")
        c.execute("UPDATE data_imports SET bbox=? WHERE id=1", (json.dumps(BB),))
        c.commit()
        self.assertEqual(cal(c, "in-pb-hr")["2024-11-10"]["viirs"]["status"], "confirmed_zero")
        c.close()


class TestCoverageStates(Base):
    def setUp(self):
        super().setUp()
        self.imp(HDR_V + viirs(30, 75, "2024-11-03"), "confirmed.csv", bbox=BB, cov_start="2024-11-01", cov_end="2024-11-30")
        self.imp(HDR_V + viirs(30.1, 75, "2024-12-05") + viirs(30.2, 75, "2024-12-10"), "assumed.csv", bbox=BB)  # no dates -> assumed

    def test_all_four_states(self):
        d = cal(self.conn, "in-pb-hr")
        self.assertEqual(d["2024-11-03"]["viirs"]["status"], "active")
        self.assertEqual(d["2024-11-04"]["viirs"]["status"], "confirmed_zero")
        self.assertEqual(d["2024-12-07"]["viirs"]["status"], "assumed_coverage")
        self.assertEqual(d["2024-10-15"]["viirs"]["status"], "no_data")
        self.assertEqual(d["2024-12-05"]["viirs"]["status"], "active")           # real detections inside assumed range stay active

    def test_assumed_zero_is_not_a_value_and_has_no_intensity(self):
        d = cal(self.conn, "in-pb-hr")
        for day, state in (("2024-12-07", "assumed_coverage"), ("2024-10-15", "no_data")):
            self.assertIsNone(d[day]["value"]); self.assertIsNone(d[day]["level"]); self.assertEqual(d[day]["value_state"], state)
        self.assertEqual(d["2024-11-04"]["value"], 0)
        self.assertEqual(d["2024-11-04"]["level"], 0)

    def test_confirmed_beats_assumed_when_both_cover_a_day(self):
        self.imp(HDR_V + viirs(30.3, 75, "2024-12-08"), "later.csv", bbox=BB, cov_start="2024-12-01", cov_end="2024-12-31")
        self.assertEqual(cal(self.conn, "in-pb-hr")["2024-12-07"]["viirs"]["status"], "confirmed_zero")

    def test_coverage_quality_exposed_to_frontend_and_reports(self):
        r = flask_app.app.test_client().get("/api/calendar?year=2024").get_json()
        self.assertGreater(r["coverage_summary"]["VIIRS"]["assumed"], 0)
        self.assertGreater(r["coverage_summary"]["VIIRS"]["confirmed"], 0)
        self.assertTrue(any("assumed coverage" in w for w in r["warnings"]))
        csv_ = flask_app.app.test_client().get("/api/reports/export?start=2024-12-01&end=2024-12-10&format=csv").get_data(as_text=True)
        self.assertIn("Coverage quality:", csv_)
        self.assertIn("assumed-coverage", csv_)
        self.assertIn("2024-12-07,no_data,,,,assumed_coverage,0", csv_)
        html_ = flask_app.app.test_client().get("/api/reports/export?start=2024-12-01&end=2024-12-10&format=html").get_data(as_text=True)
        self.assertIn("Coverage quality", html_)

    def test_monthly_view_separates_assumed_from_confirmed(self):
        m = {x["month"]: x["viirs"] for x in analytics.monthly_view(self.conn, "nasa", "in-pb-hr", [2024])}
        self.assertEqual(m["2024-11"]["quality"], "confirmed")
        self.assertEqual(m["2024-12"]["quality"], "assumed_only")
        self.assertIsNone(m["2024-12"]["count"])             # not offered as a comparable monthly value
        self.assertGreater(m["2024-12"]["assumed_coverage"], 0)
        self.assertEqual(m["2024-10"]["quality"], "no_data")


class TestAssumedExcludedFromBaselines(Base):
    COUNTS = {2019: 10, 2020: 11, 2021: 9, 2022: 10, 2023: 10, 2024: 40}

    def rows_text(self):
        return HDR_V + "".join(viirs(30 + i * 0.001, 75, f"{y}-11-05") for y, c in self.COUNTS.items() for i in range(c))

    def test_assumed_only_history_cannot_produce_anomalies(self):
        self.imp(self.rows_text(), bbox=BB)  # no coverage dates -> assumed
        a = analytics.anomalies(self.conn, "nasa", "in-pb-hr", "VIIRS", "monthly")
        self.assertEqual(a["status"], "assumed_only")
        self.assertEqual(a["anomalies"], [])
        self.assertIn("assumed", a["message"].lower())

    def test_same_data_with_declared_coverage_is_analysed(self):
        self.imp(self.rows_text(), bbox=BB, cov_start="2019-01-01", cov_end="2024-12-31")
        a = analytics.anomalies(self.conn, "nasa", "in-pb-hr", "VIIRS", "monthly")
        self.assertEqual(a["status"], "ok")
        self.assertIn("2024-11", [x["month"] for x in a["anomalies"]])
        self.assertTrue(any("assumed" in n.lower() for n in a["notes"]))

    def test_assumed_import_does_not_pollute_confirmed_baseline(self):
        self.imp(self.rows_text(), bbox=BB, cov_start="2019-01-01", cov_end="2023-12-31")      # confirmed only through 2023
        self.imp(HDR_V + "".join(viirs(30 + i * 0.001, 75, "2024-11-06") for i in range(500)), "assumed2024.csv", bbox=BB)
        a = analytics.anomalies(self.conn, "nasa", "in-pb-hr", "VIIRS", "monthly")
        self.assertNotIn("2024-11", [x["month"] for x in a["items"]])      # the assumed month is excluded, not scored
        self.assertGreaterEqual(a["excluded_assumed_months"], 1)


class TestPlatformSets(unittest.TestCase):
    def series(self):
        return [{"month": f"{y}-11", "count": c, "coverage": 1.0} for y, c in {2019: 100, 2020: 102, 2021: 98, 2022: 101, 2023: 99, 2024: 100}.items()]

    def base(self, sets):
        return {f"{y}-11": dict.fromkeys(sets, 50) for y in range(2019, 2024)}

    def test_equal_sized_but_different_platform_sets_trigger_caveat(self):
        plat = self.base(["Suomi NPP", "NOAA-20"]) | {"2024-11": {"Suomi NPP": 50, "NOAA-21": 50}}
        it = {i["month"]: i for i in analytics.monthly_anomalies(self.series(), platforms=plat)}["2024-11"]
        self.assertEqual(len(plat["2024-11"]), len(plat["2023-11"]))                  # same number of platforms
        self.assertIn("differ", it["caveat"])
        self.assertIn("added: NOAA-21", it["caveat"])
        self.assertIn("missing: NOAA-20", it["caveat"])
        self.assertEqual(it["constellation"]["observed"], ["NOAA-21", "Suomi NPP"])
        self.assertEqual(it["constellation"]["baseline_common"], ["NOAA-20", "Suomi NPP"])
        self.assertAlmostEqual(it["constellation"]["jaccard_vs_common"], 1 / 3, places=2)

    def test_identical_platform_sets_no_caveat(self):
        plat = self.base(["Suomi NPP", "NOAA-20"]) | {"2024-11": {"NOAA-20": 3, "Suomi NPP": 70}}   # counts differ, set identical
        it = {i["month"]: i for i in analytics.monthly_anomalies(self.series(), platforms=plat)}["2024-11"]
        self.assertNotIn("caveat", it)
        self.assertEqual(it["constellation"]["jaccard_vs_common"], 1.0)

    def test_heterogeneous_baseline_warned(self):
        plat = {"2019-11": {"A": 1}, "2020-11": {"B": 1}, "2021-11": {"C": 1}, "2022-11": {"A": 1}, "2023-11": {"B": 1}, "2024-11": {"A": 1}}
        it = {i["month"]: i for i in analytics.monthly_anomalies(self.series(), platforms=plat)}["2024-11"]
        self.assertIn("baseline months themselves", it["caveat"])

    def test_per_sensor_and_per_platform_counts_preserved(self):
        db.DB_PATH = os.path.join(tempfile.mkdtemp(), "p.db")
        db.init()
        txt = HDR_V + viirs(30, 75, "2024-11-05") + viirs(30.1, 75, "2024-11-05", sat="N20") + viirs(30.2, 75, "2024-11-06", sat="N20")
        importer.import_file("v.csv", txt.encode(), "nasa_archive", bbox=BB, cov_start="2024-11-01", cov_end="2024-11-30")
        importer.import_file("m.csv", (HDR_M + modis(31, 75, "2024-11-05", sat="T") + modis(31.1, 75, "2024-11-05", sat="A")).encode(),
                             "nasa_archive", bbox=BB, cov_start="2024-11-01", cov_end="2024-11-30")
        c = db.connect()
        m = {x["month"]: x for x in analytics.monthly_view(c, "nasa", "in-pb-hr", [2024])}["2024-11"]
        self.assertEqual(m["viirs"]["platforms"], {"Suomi NPP": 1, "NOAA-20": 2})
        self.assertEqual(m["modis"]["platforms"], {"Terra": 1, "Aqua": 1})
        self.assertEqual((m["viirs"]["count"], m["modis"]["count"]), (3, 2))
        c.close()

    def test_monthly_anomaly_endpoint_exposes_platform_counts_and_notes(self):
        db.DB_PATH = os.path.join(tempfile.mkdtemp(), "q.db")
        db.init()
        demo_data.load(range(2019, 2025), scale=0.3)
        a = flask_app.app.test_client().get("/api/anomalies?scope=demo&sensor=VIIRS&level=monthly").get_json()
        self.assertTrue(a["notes"])
        nov24 = [i for i in a["items"] if i["month"] == "2024-11"][0]
        self.assertIn("NOAA-21", nov24["platform_counts"])           # synthetic NOAA-21 starts in 2024
        self.assertIn("NOAA-21", nov24["caveat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
