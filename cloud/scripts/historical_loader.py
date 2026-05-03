"""
cloud/scripts/historical_loader.py

AWS-native version of scripts/historical_loader.py.
Identical logic; S3 client uses the local AWS credentials / IAM role
(no MinIO endpoint, no hard-coded access keys).

Writes:
  s3://<BUCKET>/sensor_id=<id>/date=<YYYY-MM-DD>/readings.parquet  (historical hourly)
  s3://<BUCKET>/baselines/baselines.json                            (Flink reads at startup)
  s3://<BUCKET>/stations.json                                       (station metadata)

Usage:
    pip install boto3 pyarrow requests
    export OWM_API_KEY=<key>
    export BUCKET=$(terraform -chdir=cloud/infrastructure/environments/dev output -raw data_lake_bucket_name)
    python cloud/scripts/historical_loader.py

Optional env vars:
    BUCKET           S3 bucket name (required if not set above)
    AWS_DEFAULT_REGION  (default eu-central-1)
    DAYS_HISTORY     (default 30)
    MIN_POPULATION   (default 10000)
    BASELINES_LOCAL  local path to also write baselines.json (default cloud/flink-jobs/src/baselines/baselines.json)
"""

import io
import json
import math
import os
import statistics
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import requests

# ── config ────────────────────────────────────────────────────────────────────
OWM_API_KEY    = os.environ["OWM_API_KEY"]
BUCKET         = os.environ["BUCKET"]
AWS_REGION     = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")

GEONAMES_URL   = "https://download.geonames.org/export/dump/UA.zip"
OWM_URL        = "https://api.openweathermap.org/data/2.5/air_pollution/history"
DAYS_HISTORY   = int(os.getenv("DAYS_HISTORY",   "30"))
MIN_POPULATION = int(os.getenv("MIN_POPULATION", "10000"))

REPO_ROOT      = Path(__file__).parent.parent.parent
BASELINES_LOCAL = Path(os.getenv(
    "BASELINES_LOCAL",
    str(REPO_ROOT / "cloud" / "flink-jobs" / "src" / "baselines" / "baselines.json"),
))

_ADMIN1_TO_REGION = {
    "01": "Cherkasy Oblast",    "02": "Chernihiv Oblast",    "03": "Chernivtsi Oblast",
    "05": "Dnipropetrovsk Oblast", "06": "Donetsk Oblast",   "07": "Ivano-Frankivsk Oblast",
    "08": "Kharkiv Oblast",     "09": "Kherson Oblast",      "10": "Khmelnytskyi Oblast",
    "11": "Kyiv Oblast",        "12": "Kyiv City",           "13": "Kirovohrad Oblast",
    "14": "Luhansk Oblast",     "15": "Lviv Oblast",         "16": "Mykolaiv Oblast",
    "17": "Odessa Oblast",      "18": "Poltava Oblast",      "19": "Rivne Oblast",
    "20": "Sumy Oblast",        "21": "Ternopil Oblast",     "22": "Vinnytsia Oblast",
    "23": "Volyn Oblast",       "24": "Zakarpattia Oblast",  "25": "Zaporizhzhia Oblast",
    "26": "Zhytomyr Oblast",
}

POLLUTANTS = ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]

_PARQUET_SCHEMA = pa.schema([
    pa.field("sensor_id",    pa.string()),  pa.field("station_name", pa.string()),
    pa.field("city",         pa.string()),  pa.field("region",       pa.string()),
    pa.field("country",      pa.string()),  pa.field("latitude",     pa.float64()),
    pa.field("longitude",    pa.float64()), pa.field("timestamp",    pa.string()),
    pa.field("date",         pa.string()),  pa.field("aqi",          pa.int32()),
    pa.field("co",           pa.float64()), pa.field("no",           pa.float64()),
    pa.field("no2",          pa.float64()), pa.field("o3",           pa.float64()),
    pa.field("so2",          pa.float64()), pa.field("pm2_5",        pa.float64()),
    pa.field("pm10",         pa.float64()), pa.field("nh3",          pa.float64()),
])


def make_s3():
    return boto3.client("s3", region_name=AWS_REGION)


def fetch_geonames_stations() -> list[dict]:
    print(f"Downloading GeoNames Ukraine dump...")
    resp = requests.get(GEONAMES_URL, timeout=60)
    resp.raise_for_status()
    stations: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("UA.txt") as f:
            for raw in f:
                cols = raw.decode("utf-8").rstrip("\n").split("\t")
                if len(cols) < 15 or cols[6] != "P" or cols[8] != "UA" or cols[7] in ("PPLX",):
                    continue
                try:
                    population = int(cols[14]) if cols[14] else 0
                except ValueError:
                    population = 0
                if population < MIN_POPULATION:
                    continue
                stations.append({
                    "sensor_id":    f"ua_{cols[0]}",
                    "station_name": cols[1],
                    "city":         cols[1],
                    "region":       _ADMIN1_TO_REGION.get(cols[10], ""),
                    "country":      "UA",
                    "latitude":     float(cols[4]),
                    "longitude":    float(cols[5]),
                })
    stations.sort(key=lambda s: s["city"])
    print(f"Found {len(stations)} stations (population ≥ {MIN_POPULATION:,})")
    return stations


def fetch_history(lat: float, lon: float) -> list[dict]:
    end   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=DAYS_HISTORY)).timestamp())
    resp  = requests.get(OWM_URL, params={"lat": lat, "lon": lon,
                                          "start": start, "end": end, "appid": OWM_API_KEY}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("list", [])


def compute_baselines(readings: list[dict]) -> dict:
    buckets: dict[str, list] = {p: [] for p in POLLUTANTS}
    aqi_vals = []
    for entry in readings:
        c = entry.get("components", {})
        for p in POLLUTANTS:
            v = c.get(p)
            if v is not None:
                buckets[p].append(v)
        aqi = entry.get("main", {}).get("aqi")
        if aqi is not None:
            aqi_vals.append(aqi)

    def _stats(vals):
        clean = [v for v in vals if v is not None and not math.isnan(v)]
        if len(clean) < 2:
            return {"mean": None, "std": None}
        mean = statistics.mean(clean)
        return {"mean": round(mean, 4), "std": max(round(statistics.stdev(clean), 4), 0.1)}

    result = {p: _stats(buckets[p]) for p in POLLUTANTS}
    result["aqi"] = _stats(aqi_vals)
    return result


def upload_parquet(s3, rows: list[dict], sensor_id: str, date: str):
    table = pa.Table.from_pylist(rows, schema=_PARQUET_SCHEMA)
    buf   = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    key = f"sensor_id={sensor_id}/date={date}/readings.parquet"
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    print(f"  s3://{BUCKET}/{key}  ({len(rows)} rows)")


def _owm_to_row(entry: dict, station: dict) -> dict:
    c  = entry.get("components", {})
    dt = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
    return {**station, "timestamp": dt.isoformat(), "date": dt.strftime("%Y-%m-%d"),
            "aqi": entry.get("main", {}).get("aqi"),
            **{p: c.get(p) for p in POLLUTANTS}}


def main():
    s3 = make_s3()

    resp = s3.list_objects_v2(Bucket=BUCKET, MaxKeys=1)
    if resp.get("KeyCount", 0) > 0:
        # Check specifically for Parquet files
        resp2 = s3.list_objects_v2(Bucket=BUCKET, Prefix="sensor_id=", MaxKeys=1)
        if resp2.get("KeyCount", 0) > 0:
            print(f"Bucket s3://{BUCKET} already has sensor data — skipping.")
            print("Delete the sensor_id= prefix to re-run.")
            return

    stations = fetch_geonames_stations()
    all_baselines: dict[str, dict] = {}

    for station in stations:
        sid = station["sensor_id"]
        print(f"\nFetching {sid} ({station['station_name']})...")
        try:
            raw = fetch_history(station["latitude"], station["longitude"])
        except Exception as e:
            print(f"  ERROR: {e} — skipping")
            continue
        if not raw:
            print("  no data — skipping")
            continue
        print(f"  {len(raw)} hourly readings")
        all_baselines[sid] = compute_baselines(raw)
        by_date: dict[str, list] = {}
        for entry in raw:
            row  = _owm_to_row(entry, station)
            by_date.setdefault(row["date"], []).append(row)
        for date, rows in by_date.items():
            upload_parquet(s3, rows, sid, date)
        time.sleep(0.2)

    baselines_json = json.dumps(all_baselines, indent=2)

    # Write locally (for packaging into Flink ZIP)
    BASELINES_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    BASELINES_LOCAL.write_text(baselines_json)
    print(f"\nBaselines written locally → {BASELINES_LOCAL}  ({len(all_baselines)} stations)")

    # Upload to S3 (Flink reads this at startup via BASELINES_FILE env var)
    s3.put_object(Bucket=BUCKET, Key="baselines/baselines.json",
                  Body=baselines_json.encode())
    print(f"Baselines uploaded  → s3://{BUCKET}/baselines/baselines.json")

    station_meta = [s for s in stations if s["sensor_id"] in all_baselines]
    s3.put_object(Bucket=BUCKET, Key="stations.json",
                  Body=json.dumps(station_meta).encode())
    print(f"Stations uploaded   → s3://{BUCKET}/stations.json  ({len(station_meta)} stations)")


if __name__ == "__main__":
    main()