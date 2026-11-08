import io
import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from test_agnilens import Base, HDR_V, viirs  # noqa: E402
import app as flask_app  # noqa: E402
import db  # noqa: E402
import importer  # noqa: E402
import api  # noqa: E402


class TestAuditRegressions(Base):
    def setUp(self):
        super().setUp()
        self.client = flask_app.app.test_client()

    def test_overview_counts_and_defaults_are_region_scoped(self):
        india = [68.0, 6.5, 97.5, 37.1]
        self.imp(HDR_V + viirs(30.0, 75.0, "2024-11-05") + viirs(25.0, 80.0, "2024-11-06"),
                 bbox=india, extent_label="India")
        r = self.client.get("/api/overview?scope=nasa&region=in-punjab").get_json()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["by_source"][0]["last"], "2024-11-05")
        self.assertEqual(r["provenance"][0]["links"], 1)

    def test_nonfinite_and_partial_query_values_return_clear_400(self):
        requests = [
            self.client.get("/api/calendar?year=nan"),
            self.client.get("/api/calendar?year=2024.5"),
            self.client.get("/api/monthly?years=2024,nope"),
            self.client.get("/api/monthly?years=" + ",".join(str(y) for y in range(2000, 2021))),
            self.client.get("/api/map/observations?start=2024-01-01"),
            self.client.get("/api/comparison?start=2024-02-01&end=2024-01-01"),
            self.client.get("/api/regions/summary?end=2024-01-01"),
            self.client.get("/api/reports/export?start=1900-01-01&end=2024-01-01"),
            self.client.get("/api/reports/export?start=2024-01-01&end=2024-01-31&format=json"),
            self.client.post("/api/harmonize?start=2024-01-01&end=2024-01-31&dist=nan"),
        ]
        for response in requests:
            with self.subTest(path=response.request.path, query=response.request.query_string):
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

    def test_malformed_json_and_csv_are_rejected_as_inputs(self):
        cases = [
            ("bad.json", b'{"records": "not-an-array"}'),
            ("bad.geojson", b'{"features": "not-an-array"}'),
            ("bad.json", b'[1,2]'),
            ("bad.csv", b"not,a,firms,header\n1,2,3,4\n"),
        ]
        for name, content in cases:
            with self.subTest(filename=name, content=content[:20]):
                with self.assertRaises(ValueError):
                    importer.parse_records(name, content)

    def test_map_thinning_samples_matching_rows_instead_of_global_ids(self):
        rows = []
        for i in range(101):
            rows.append(viirs(30 + i * 0.0005, 75, "2024-11-05", time=f"{i % 24:02d}00"))
            rows.append(viirs(25 + i * 0.0005, 80, "2024-11-05", time=f"{i % 24:02d}00"))
        self.imp(HDR_V + "".join(rows), bbox=db.STUDY_BBOX)
        response = self.client.get("/api/map/observations?limit=100")
        result = response.get_json()
        self.assertEqual(result["total_matching"], 101)
        self.assertEqual(result["returned"], 51)
        self.assertEqual(result["thinned_every"], 2)
        self.assertTrue(all(27.6 <= item["lat"] <= 32.6 for item in result["observations"]))

    def test_upload_limit_returns_json_error(self):
        old = flask_app.app.config["MAX_CONTENT_LENGTH"]
        flask_app.app.config["MAX_CONTENT_LENGTH"] = 10
        try:
            response = self.client.post("/api/import", data={"file": (io.BytesIO(b"large payload"), "x.csv")})
            self.assertEqual(response.status_code, 413)
            self.assertIn("configured limit", response.get_json()["error"])
        finally:
            flask_app.app.config["MAX_CONTENT_LENGTH"] = old

    def test_concurrent_import_limit_returns_retryable_status(self):
        class Full:
            def acquire(self, blocking=False):
                return False
        old = api._IMPORT_SLOTS
        api._IMPORT_SLOTS = Full()
        try:
            response = self.client.post("/api/import", data={
                "extent": "in-pb-hr", "file": (io.BytesIO((HDR_V + viirs(30, 75, "2024-11-05")).encode()), "one.csv")})
            self.assertEqual(response.status_code, 429)
            self.assertIn("already running", response.get_json()["error"])
        finally:
            api._IMPORT_SLOTS = old

    def test_all_pages_and_local_assets_are_served(self):
        paths = ["/", "/map", "/harmonize", "/calendar", "/compare", "/regional", "/anomalies",
                 "/data", "/reports", "/experimental", "/shared.css", "/shared.js"]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data)
                response.close()

    def test_all_api_routes_complete_without_external_network(self):
        data = (HDR_V + viirs(30, 75, "2024-11-05") +
                "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"
                "30.001,75.001,320,1,1,2024-11-05,0810,A,MODIS,80,6.1,300,8,D\n")
        iid = importer.import_file("route-check.csv", data.encode(), "nasa_archive", cov_start="2024-11-01",
                                   cov_end="2024-11-30", bbox=db.STUDY_BBOX)
        oid = self.conn.execute("SELECT id FROM satellite_observations ORDER BY id LIMIT 1").fetchone()[0]
        checks = [
            ("GET", "/api/health"), ("GET", "/api/regions"), ("GET", "/api/overview?region=in-pb-hr"),
            ("GET", "/api/map/observations?start=2024-11-01&end=2024-11-30"),
            ("GET", "/api/imports"), ("GET", f"/api/imports/{iid}"),
            ("GET", f"/api/observations/{oid}/sources"), ("GET", "/api/calendar?year=2024"),
            ("GET", "/api/monthly?years=2024"), ("GET", "/api/anomalies?level=monthly"),
            ("POST", "/api/harmonize?start=2024-11-05&end=2024-11-05"),
            ("GET", "/api/comparison?start=2024-11-01&end=2024-11-30"),
            ("GET", "/api/regions/summary?start=2024-11-01&end=2024-11-30"),
            ("GET", "/api/reports/export?start=2024-11-01&end=2024-11-30&format=csv"),
            ("GET", "/api/reports/export?start=2024-11-01&end=2024-11-30&format=html"),
            ("POST", f"/api/imports/{iid}/extent"), ("POST", "/api/demo/load"), ("DELETE", "/api/demo"),
        ]
        previous = os.environ.get("FIRMS_MAP_KEY")
        os.environ["FIRMS_MAP_KEY"] = "test-key"
        try:
            with patch("api.importer.ingest_nrt", return_value=[{"source": "VIIRS_SNPP_NRT", "status": "ok"}]), \
                 patch("api.demo_data.load", return_value=123):
                checks.append(("POST", "/api/nrt/refresh?days=1"))
                for method, path in checks:
                    with self.subTest(method=method, path=path):
                        if path.endswith("/extent"):
                            response = self.client.open(path, method=method, json={"extent": "in-pb-hr"})
                        else:
                            response = self.client.open(path, method=method)
                        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                fires = ([{"lat": 30, "lon": 75, "frp": 2}], False, [], False, "2026-11-08T00:00:00+00:00")
                weather = ([{"t": "2026-11-08T14:00", "speed": 5, "dir": 300, "pm25": 12}], False, False, None)
                with patch("app.get_fires", return_value=fires), patch("app.get_weather", return_value=weather):
                    self.assertEqual(self.client.get("/api/status").status_code, 200)
        finally:
            if previous is None:
                os.environ.pop("FIRMS_MAP_KEY", None)
            else:
                os.environ["FIRMS_MAP_KEY"] = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)
