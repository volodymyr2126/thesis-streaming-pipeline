"""
cloud/scripts/expand_to_minutely.py

AWS-native version of scripts/expand_to_minutely.py.
Reads hourly Parquet from S3 (sensor_id=.../date=.../readings.parquet),
expands each hourly row to 60 minute-level rows with small Gaussian jitter,
and writes the result to the same bucket under the same key prefix.

The producer's replay.py reads from MINIO_BUCKET at the sensor_id= prefix,
so source and destination can be the same bucket (hourly and minutely files
share the same key structure — the minutely ones simply replace the hourly ones
in-place after this script runs).

Usage:
    export BUCKET=$(terraform -chdir=cloud/infrastructure/environments/dev output -raw data_lake_bucket_name)
    python cloud/scripts/expand_to_minutely.py

Optional env vars:
    BUCKET               S3 bucket name (required)
    AWS_DEFAULT_REGION   (default eu-central-1)
    SRC_PREFIX           prefix inside BUCKET for hourly files (default sensor_id=)
    DST_PREFIX           prefix inside BUCKET for minutely output (default sensor_id=)
                         When SRC_PREFIX == DST_PREFIX the files are expanded in place.
    JITTER_FRAC          (default 0.05)
    WORKERS              (default 8)
"""

import io
import math
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

BUCKET      = os.environ["BUCKET"]
AWS_REGION  = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
SRC_PREFIX  = os.getenv("SRC_PREFIX", "sensor_id=")
DST_PREFIX  = os.getenv("DST_PREFIX", "sensor_id=")
JITTER_FRAC = float(os.getenv("JITTER_FRAC", "0.05"))
WORKERS     = int(os.getenv("WORKERS", "8"))

POLLUTANTS = ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]

_SCHEMA = pa.schema([
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


def _sub_index(value: float, breakpoints: list) -> int:
    for level, threshold in enumerate(breakpoints, start=1):
        if value <= threshold:
            return level
    return 5


def compute_aqi(pm2_5: float, pm10: float, no2: float, o3: float, so2: float) -> int:
    return max(
        _sub_index(pm2_5, [10,  20,  25,  50]),
        _sub_index(pm10,  [20,  40,  50,  100]),
        _sub_index(no2,   [40,  90,  120, 230]),
        _sub_index(o3,    [60,  100, 130, 240]),
        _sub_index(so2,   [100, 200, 350, 500]),
    )


def _jitter(value: float) -> float:
    if value == 0.0:
        return 0.0
    return max(0.0, round(random.gauss(value, abs(value) * JITTER_FRAC), 2))


def expand_row(row: dict) -> list[dict]:
    base_ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    base_ts = base_ts.replace(minute=0, second=0, microsecond=0)
    minutes = []
    for m in range(60):
        ts    = base_ts + timedelta(minutes=m)
        co    = _jitter(row.get("co")    or 0.0)
        no    = _jitter(row.get("no")    or 0.0)
        no2   = _jitter(row.get("no2")   or 0.0)
        o3    = _jitter(row.get("o3")    or 0.0)
        so2   = _jitter(row.get("so2")   or 0.0)
        pm2_5 = _jitter(row.get("pm2_5") or 0.0)
        pm10  = _jitter(row.get("pm10")  or 0.0)
        nh3   = _jitter(row.get("nh3")   or 0.0)
        minutes.append({
            "sensor_id":    row["sensor_id"],    "station_name": row["station_name"],
            "city":         row["city"],          "region":       row.get("region", ""),
            "country":      row.get("country", "UA"),
            "latitude":     row["latitude"],      "longitude":    row["longitude"],
            "timestamp":    ts.isoformat(),       "date":         ts.strftime("%Y-%m-%d"),
            "aqi":          compute_aqi(pm2_5, pm10, no2, o3, so2),
            "co": co, "no": no, "no2": no2, "o3": o3,
            "so2": so2, "pm2_5": pm2_5, "pm10": pm10, "nh3": nh3,
        })
    return minutes


def list_source_keys(s3) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=SRC_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                keys.append(obj["Key"])
    return keys


def already_minutely(s3, key: str) -> bool:
    """A file is already minutely-expanded if it has ≥ 60 rows."""
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        rows = pq.read_table(io.BytesIO(body)).num_rows
        return rows >= 60
    except Exception:
        return False


def process_key(key: str) -> tuple[str, int]:
    s3 = make_s3()

    if already_minutely(s3, key):
        return (key, 0)

    body     = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    src_rows = pq.read_table(io.BytesIO(body)).to_pylist()

    expanded: list[dict] = []
    for row in src_rows:
        expanded.extend(expand_row(row))

    if not expanded:
        return (key, 0)

    dst_key = DST_PREFIX + key[len(SRC_PREFIX):]  # same relative path, different prefix
    table   = pa.Table.from_pylist(expanded, schema=_SCHEMA)
    buf     = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    s3.put_object(Bucket=BUCKET, Key=dst_key, Body=buf.getvalue())
    return (dst_key, len(expanded))


def main():
    s3 = make_s3()

    print(f"Bucket : s3://{BUCKET}")
    print(f"Source : {SRC_PREFIX}  →  Dest: {DST_PREFIX}")
    print(f"Jitter : ±{JITTER_FRAC*100:.0f}%  Workers: {WORKERS}\n")

    keys = list_source_keys(s3)
    if not keys:
        print("No Parquet files found — run cloud/scripts/historical_loader.py first.")
        sys.exit(1)

    print(f"Found {len(keys):,} source files\n")
    done = skipped = total_rows = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process_key, k): k for k in keys}
        for i, fut in enumerate(as_completed(futures), start=1):
            key, rows = fut.result()
            if rows == 0:
                skipped += 1
            else:
                done += 1
                total_rows += rows
            if i % 500 == 0 or i == len(keys):
                print(f"  [{i:>6}/{len(keys)}  {i/len(keys)*100:5.1f}%]  "
                      f"written={done}  skipped={skipped}  rows≈{total_rows:,}")

    print(f"\nDone. {done} files written, {skipped} skipped. Total rows: {total_rows:,}")


if __name__ == "__main__":
    main()