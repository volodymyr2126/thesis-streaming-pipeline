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
from botocore.exceptions import ClientError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT",  "http://localhost:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin")
SRC_BUCKET     = os.getenv("SRC_BUCKET",  "air-quality-historical")
DST_BUCKET     = os.getenv("DST_BUCKET",  "air-quality-minutely")
JITTER_FRAC    = float(os.getenv("JITTER_FRAC", "0.05"))
WORKERS        = int(os.getenv("WORKERS", "8"))

POLLUTANTS = ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]

_SCHEMA = pa.schema([
    pa.field("sensor_id",    pa.string()),
    pa.field("station_name", pa.string()),
    pa.field("city",         pa.string()),
    pa.field("region",       pa.string()),
    pa.field("country",      pa.string()),
    pa.field("latitude",     pa.float64()),
    pa.field("longitude",    pa.float64()),
    pa.field("timestamp",    pa.string()),
    pa.field("date",         pa.string()),
    pa.field("aqi",          pa.int32()),
    pa.field("co",           pa.float64()),
    pa.field("no",           pa.float64()),
    pa.field("no2",          pa.float64()),
    pa.field("o3",           pa.float64()),
    pa.field("so2",          pa.float64()),
    pa.field("pm2_5",        pa.float64()),
    pa.field("pm10",         pa.float64()),
    pa.field("nh3",          pa.float64()),
])



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
    noisy = random.gauss(value, abs(value) * JITTER_FRAC)
    return max(0.0, round(noisy, 2))


def expand_row(row: dict) -> list[dict]:
    """Return 60 minute-level dicts from one hourly row."""
    base_ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    base_ts = base_ts.replace(minute=0, second=0, microsecond=0)

    minutes = []
    for m in range(60):
        ts = base_ts + timedelta(minutes=m)
        co    = _jitter(row.get("co")   or 0.0)
        no    = _jitter(row.get("no")   or 0.0)
        no2   = _jitter(row.get("no2")  or 0.0)
        o3    = _jitter(row.get("o3")   or 0.0)
        so2   = _jitter(row.get("so2")  or 0.0)
        pm2_5 = _jitter(row.get("pm2_5") or 0.0)
        pm10  = _jitter(row.get("pm10")  or 0.0)
        nh3   = _jitter(row.get("nh3")   or 0.0)

        minutes.append({
            "sensor_id":    row["sensor_id"],
            "station_name": row["station_name"],
            "city":         row["city"],
            "region":       row.get("region", ""),
            "country":      row.get("country", "UA"),
            "latitude":     row["latitude"],
            "longitude":    row["longitude"],
            "timestamp":    ts.isoformat(),
            "date":         ts.strftime("%Y-%m-%d"),
            "aqi":          compute_aqi(pm2_5, pm10, no2, o3, so2),
            "co":           co,
            "no":           no,
            "no2":          no2,
            "o3":           o3,
            "so2":          so2,
            "pm2_5":        pm2_5,
            "pm10":         pm10,
            "nh3":          nh3,
        })
    return minutes



def make_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name="us-east-1",
    )


def ensure_bucket(s3, bucket: str):
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        print(f"Created bucket '{bucket}'")


def key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def list_source_keys(s3) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=SRC_BUCKET):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                keys.append(obj["Key"])
    return keys



def process_key(key: str) -> tuple[str, int]:
    """Read one source Parquet, expand, upload to dst bucket. Returns (key, rows_written)."""
    s3 = make_client()

    if key_exists(s3, DST_BUCKET, key):
        return (key, 0)

    body = s3.get_object(Bucket=SRC_BUCKET, Key=key)["Body"].read()
    src_rows = pq.read_table(io.BytesIO(body)).to_pylist()

    expanded: list[dict] = []
    for row in src_rows:
        expanded.extend(expand_row(row))

    if not expanded:
        return (key, 0)

    table = pa.Table.from_pylist(expanded, schema=_SCHEMA)
    buf   = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    s3.put_object(Bucket=DST_BUCKET, Key=key, Body=buf.getvalue())
    return (key, len(expanded))



def main():
    s3 = make_client()

    print(f"Source : s3://{SRC_BUCKET}")
    print(f"Dest   : s3://{DST_BUCKET}")
    print(f"Jitter : ±{JITTER_FRAC*100:.0f}%  Workers: {WORKERS}")

    ensure_bucket(s3, DST_BUCKET)

    keys = list_source_keys(s3)
    if not keys:
        print("No Parquet files found in source bucket — run historical_loader.py first.")
        sys.exit(1)

    print(f"Found {len(keys):,} source files — expanding each hourly row → 60 minute rows\n")

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
                pct = i / len(keys) * 100
                print(f"  [{i:>6}/{len(keys)}  {pct:5.1f}%]  "
                      f"written={done}  skipped={skipped}  rows≈{total_rows:,}")

    print(f"\nDone.  {done} files written, {skipped} skipped (already existed).")
    print(f"Total minute-level rows: {total_rows:,}")
    if total_rows:
        rate_per_min = total_rows / (31 * 24 * 60) * 60  # rows/min at REPLAY_SPEED=60
        print(f"Expected replay rate at REPLAY_SPEED=60: ~{rate_per_min:,.0f} events/min")


if __name__ == "__main__":
    main()
