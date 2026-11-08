"""Reproducible MODIS/VIIRS archive comparison; writes metrics, never labels them validation."""
import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import harmonize as H
from importer import parse_records, to_observation


def read_archive(path, sensor, bbox):
    content = Path(path).read_bytes()
    records = parse_records(path, content)
    accepted, rejected, seen = [], Counter(), set()
    for raw in records:
        o, reason = to_observation(raw, forced_sensor=sensor)
        if o is None:
            rejected[reason] += 1
            continue
        if not (bbox[0] <= o["lon"] <= bbox[2] and bbox[1] <= o["lat"] <= bbox[3]):
            rejected["outside_declared_bbox"] += 1
            continue
        ident = (o["sensor"], o["satellite"], o["acq_utc"], o["lat"], o["lon"])
        if ident in seen:
            rejected["duplicate_source_identity"] += 1
            continue
        seen.add(ident)
        ts = datetime.strptime(o["acq_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        accepted.append({"id": f"{sensor}:{len(accepted)}", "sensor": sensor, "satellite": o["satellite"], "ts": ts,
                         "lat": o["lat"], "lon": o["lon"], "frp": o["frp"], "brightness_k": o["brightness"],
                         "confidence_raw": o["confidence_raw"], "flags": o["flags"].split(",") if o["flags"] else []})
    dates = [o["ts"].date().isoformat() for o in accepted]
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "records_received": len(records),
            "records_accepted": len(accepted), "records_duplicate": rejected["duplicate_source_identity"],
            "records_rejected": sum(rejected.values()) - rejected["duplicate_source_identity"], "rejection_reasons": dict(rejected),
            "date_min": min(dates) if dates else None, "date_max": max(dates) if dates else None,
            "platforms": dict(Counter(o["satellite"] for o in accepted)), "observations": accepted}


def experiment(modis_path, viirs_path, bbox, configs):
    m, v = read_archive(modis_path, "MODIS", bbox), read_archive(viirs_path, "VIIRS", bbox)
    rows = []
    for distance, minutes in configs:
        result = H.match(m["observations"], v["observations"], distance, minutes)
        matched_m = {p["modis_id"] for p in result["pairs"]}
        matched_v = {p["viirs_id"] for p in result["pairs"]}
        distances = [p["distance_m"] for p in result["pairs"]]
        deltas = [p["dt_min"] for p in result["pairs"]]
        rows.append({"parameters": result["params"], "candidate_pairs": len(result["pairs"]),
                     "candidate_groups": result["summary"]["groups"], "modis_matched_observations": len(matched_m),
                     "viirs_matched_observations": len(matched_v),
                     "modis_matched_fraction": round(len(matched_m) / len(m["observations"]), 4) if m["observations"] else None,
                     "viirs_matched_fraction": round(len(matched_v) / len(v["observations"]), 4) if v["observations"] else None,
                     "median_pair_distance_m": statistics.median(distances) if distances else None,
                     "median_pair_time_difference_min": statistics.median(deltas) if deltas else None})
    daily = defaultdict(lambda: {"modis": 0, "viirs": 0})
    for dataset in (m, v):
        for o in dataset["observations"]:
            daily[o["ts"].date().isoformat()][o["sensor"].lower()] += 1
    return {"experiment": "archive_pair_threshold_sensitivity", "interpretation": "Algorithmic consistency only; not scientific validation against fire ground truth.",
            "bbox_wsen": bbox, "files": {"modis": {k: val for k, val in m.items() if k != "observations"},
                                       "viirs": {k: val for k, val in v.items() if k != "observations"}},
            "sensitivity": rows, "daily_detection_counts": [{"date": d, **n} for d, n in sorted(daily.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modis_csv")
    parser.add_argument("viirs_csv")
    parser.add_argument("--bbox", default="73.8,27.6,77.6,32.6", help="west,south,east,north (default Punjab + Haryana approximate box)")
    parser.add_argument("--out", help="write JSON report to this path; otherwise print to stdout")
    parser.add_argument("--thresholds", default="500:30,1000:120,2000:240", help="comma-separated distance_m:time_min configurations")
    args = parser.parse_args()
    bbox = [float(x) for x in args.bbox.split(",")]
    if len(bbox) != 4 or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90):
        parser.error("--bbox must be valid west,south,east,north coordinates")
    configs = [tuple(float(x) for x in pair.split(":")) for pair in args.thresholds.split(",")]
    if any(len(pair) != 2 or pair[0] < 0 or pair[1] < 0 for pair in configs):
        parser.error("--thresholds entries must be nonnegative distance_m:time_min pairs")
    report = json.dumps(experiment(args.modis_csv, args.viirs_csv, bbox, configs), indent=2)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
