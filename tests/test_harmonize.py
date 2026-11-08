import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import harmonize as H


def row(lat, lon, time="0530", date="2026-11-05", **kw):
    return {"latitude": lat, "longitude": lon, "acq_date": date, "acq_time": time, "frp": "5.0",
            "confidence": "n", "brightness": "330", "bright_ti4": "340", "satellite": "T", **kw}


def run(m, v, **kw):
    mo, _ = H.normalize(m, "MODIS"); vi, _ = H.normalize(v, "VIIRS")
    return H.match(mo, vi, **kw), mo, vi


class Tests(unittest.TestCase):
    def test_close_pair_matches(self):  # ~0.0045 deg lat = ~500 m
        r, _, _ = run([row(30.0, 75.0)], [row(30.0045, 75.0, "0535")])
        self.assertEqual(r["summary"]["candidate_pairs"], 1)
        self.assertEqual(r["summary"]["groups"], 1)
        self.assertAlmostEqual(r["pairs"][0]["distance_m"], 500, delta=15)
        self.assertEqual(r["pairs"][0]["dt_min"], 5)

    def test_far_apart_no_match(self):  # ~5.5 km
        r, _, _ = run([row(30.0, 75.0)], [row(30.05, 75.0)])
        self.assertEqual(r["summary"]["candidate_pairs"], 0)
        self.assertEqual(r["summary"]["modis_only"], 1)
        self.assertEqual(r["summary"]["viirs_only"], 1)

    def test_time_window(self):  # 4 h apart, default window 120 min
        r, _, _ = run([row(30.0, 75.0, "0300")], [row(30.001, 75.0, "0700")])
        self.assertEqual(r["summary"]["candidate_pairs"], 0)
        r2, _, _ = run([row(30.0, 75.0, "0300")], [row(30.001, 75.0, "0700")], max_dt_min=300)
        self.assertEqual(r2["summary"]["candidate_pairs"], 1)

    def test_many_to_one_preserved(self):  # 2 MODIS near 1 VIIRS -> 2 pairs, 1 group, nothing dropped
        r, _, _ = run([row(30.0, 75.0), row(30.003, 75.0)], [row(30.0015, 75.0)])
        self.assertEqual(r["summary"]["candidate_pairs"], 2)
        self.assertEqual(r["summary"]["groups"], 1)
        self.assertEqual(r["summary"]["many_to_one_groups"], 1)
        self.assertEqual(len(r["observations"]), 3)

    def test_invalid_and_duplicates(self):
        rows = [row(95, 75), row("x", 75), row(30, 75, date="bad"), row(30, 75), row(30, 75)]
        clean, rej = H.normalize(rows, "VIIRS")
        self.assertEqual(len(clean), 1)
        self.assertEqual(rej, {"invalid_coordinates": 2, "invalid_timestamp": 1, "duplicate": 1})

    def test_missing_values_flagged_not_dropped(self):
        clean, _ = H.normalize([row(30, 75, frp="")], "MODIS")
        self.assertIn("missing_frp", clean[0]["flags"])

    def test_raw_rows_not_mutated(self):
        raw = [row(30, 75)]
        snap = dict(raw[0])
        H.normalize(raw, "MODIS")
        self.assertEqual(raw[0], snap)

    def test_confidence_not_merged(self):
        m, _ = H.normalize([row(30, 75, confidence="85")], "MODIS")
        v, _ = H.normalize([row(30, 75, confidence="h")], "VIIRS")
        self.assertEqual(m[0]["confidence_raw"], "85")
        self.assertEqual(v[0]["confidence_raw"], "h")

    def test_daily_summary_separate_sensors(self):
        r, _, _ = run([row(30, 75), row(31, 75)], [row(30, 75.0)])
        d = H.daily_summary(r["observations"])
        self.assertEqual(d[0]["modis"]["count"], 2)
        self.assertEqual(d[0]["viirs"]["count"], 1)


class TestExactIdentity(unittest.TestCase):
    def test_nearby_distinct_coordinates_both_survive(self):  # differ by 0.00001 deg, far below the old 4-decimal rounding
        clean, rej = H.normalize([row(30.00001, 75.0), row(30.00002, 75.0)], "VIIRS")
        self.assertEqual(len(clean), 2)
        self.assertEqual(rej, {})

    def test_true_duplicate_with_different_formatting_removed(self):
        clean, rej = H.normalize([row("30.0", "75.0"), row(30, 75)], "VIIRS")
        self.assertEqual((len(clean), rej), (1, {"duplicate": 1}))

    def test_same_place_and_time_different_satellite_kept(self):
        clean, _ = H.normalize([row(30, 75, satellite="T"), row(30, 75, satellite="A")], "MODIS")
        self.assertEqual(len(clean), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
