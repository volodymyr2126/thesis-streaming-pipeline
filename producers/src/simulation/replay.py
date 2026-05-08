"""Replay historical air quality readings from S3 (or MinIO) Parquet at configurable speed."""
import io
import logging
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3
import pyarrow.parquet as pq

from producers.src.data.models import SensorReading

logger = logging.getLogger(__name__)

MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "")   # empty = use real AWS S3
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY",  "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY",  "minioadmin")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",      "air-quality-minutely")
REPLAY_SPEED     = float(os.getenv("REPLAY_SPEED", "1000"))  # 1000× real time
LOAD_WORKERS     = int(os.getenv("LOAD_WORKERS", "16"))


def _make_s3_client():
    if MINIO_ENDPOINT:
        return boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
        )
    return boto3.client("s3")


def _fetch_key(key: str) -> list[dict]:
    body = _make_s3_client().get_object(Bucket=MINIO_BUCKET, Key=key)["Body"].read()
    return pq.read_table(io.BytesIO(body)).to_pylist()


def _list_keys_by_date() -> dict[str, list[str]]:
    """Return {date_str: [key, ...]} sorted by date, collected from S3/MinIO listing."""
    s3 = _make_s3_client()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        keys = [
            obj["Key"]
            for page in paginator.paginate(Bucket=MINIO_BUCKET)
            for obj in page.get("Contents", [])
            if obj["Key"].endswith(".parquet")
        ]
    except Exception as e:
        logger.error(f"Cannot connect to S3 bucket {MINIO_BUCKET}: {e}")
        return {}

    if not keys:
        logger.warning("No Parquet files in MinIO — run scripts/historical_loader.py first")
        return {}

    # key format: sensor_id=<id>/date=<YYYY-MM-DD>/readings.parquet
    by_date: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        parts = key.split("/")
        date = parts[1].replace("date=", "") if len(parts) >= 2 else "unknown"
        by_date[date].append(key)

    return dict(sorted(by_date.items()))


def _load_day(date_keys: list[str]) -> list[dict]:
    """Parallel-fetch all sensor files for one day, return rows sorted by timestamp."""
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=LOAD_WORKERS) as pool:
        for chunk in as_completed(pool.submit(_fetch_key, k) for k in date_keys):
            rows.extend(chunk.result())
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def _to_reading(row: dict) -> SensorReading:
    pm2_5 = float(row.get("pm2_5") or 0.0)
    pm10  = float(row.get("pm10")  or 0.0)
    no2   = float(row.get("no2")   or 0.0)
    o3    = float(row.get("o3")    or 0.0)
    so2   = float(row.get("so2")   or 0.0)

    return SensorReading(
        reading_id=str(uuid.uuid4()),
        sensor_id=row["sensor_id"],
        station_name=row["station_name"],
        city=row["city"],
        region=row.get("region", ""),
        country=row.get("country", "UA"),
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        timestamp=datetime.now(timezone.utc).isoformat(),
        co=   round(float(row.get("co")  or 0.0), 2),
        no=   round(float(row.get("no")  or 0.0), 2),
        no2=  round(no2,  2),
        o3=   round(o3,   2),
        so2=  round(so2,  2),
        pm2_5=round(pm2_5, 2),
        pm10= round(pm10,  2),
        nh3=  round(float(row.get("nh3") or 0.0), 2),
        aqi=int(row.get("aqi") or 0),
        is_anomaly=False,
    )


async def replay_stream():
    """
    Async generator that yields SensorReadings replayed from MinIO Parquet files
    at REPLAY_SPEED × real time, looping indefinitely.

    Loads one day at a time (~414 sensors × 60 min ≈ 25k rows) to keep
    memory usage flat regardless of how much historical data is in MinIO.
    """
    import asyncio

    keys_by_date = _list_keys_by_date()
    if not keys_by_date:
        return

    dates = sorted(keys_by_date.keys())
    logger.info(f"Found {len(dates)} days ({dates[0]} → {dates[-1]}), "
                f"starting replay at {REPLAY_SPEED}× real time")

    t0_hist: datetime | None = None
    wall_start: float | None = None

    while True:
        for date in dates:
            logger.info(f"Loading day {date} ({len(keys_by_date[date])} files)...")
            rows = _load_day(keys_by_date[date])
            if not rows:
                continue

            for row in rows:
                t_hist = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))

                if t0_hist is None:
                    t0_hist = t_hist
                    wall_start = time.monotonic()

                hist_elapsed = (t_hist - t0_hist).total_seconds()
                target_wall  = wall_start + hist_elapsed / REPLAY_SPEED

                delay = target_wall - time.monotonic()
                if delay > 0.001:
                    await asyncio.sleep(delay)

                yield _to_reading(row)

        logger.info("Replay cycle complete — restarting from beginning")
        t0_hist = None
        wall_start = None
