import io
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from config import (
    AQI_BREAKPOINTS,
    AQI_MAX_LEVEL,
    DST_BUCKET,
    HISTORY_PERIOD_DAYS,
    JITTER_FRAC,
    MINIO_ACCESS,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET,
    MINUTES_PER_HOUR,
    PARQUET_SCHEMA,
    REPLAY_SPEED_DEFAULT,
    SRC_BUCKET,
    WORKERS,
)


def _sub_index(value: float, breakpoints: list) -> int:
    """Map a pollutant concentration to its 1-5 AQI sub-index.

    Args:
        value: Pollutant concentration.
        breakpoints: Ascending list of upper bounds for levels 1..4.

    Returns:
        Integer AQI level in the closed range ``[1, AQI_MAX_LEVEL]``.
    """
    for level, threshold in enumerate(breakpoints, start=1):
        if value <= threshold:
            return level
    return AQI_MAX_LEVEL


def compute_aqi(pm2_5: float, pm10: float, no2: float, o3: float, so2: float) -> int:
    """Compute the European Air Quality Index for a set of pollutants.

    The composite AQI is the maximum sub-index across PM2.5, PM10, NO2,
    O3 and SO2 according to :data:`AQI_BREAKPOINTS`.

    Args:
        pm2_5: PM2.5 concentration in µg/m³.
        pm10: PM10 concentration in µg/m³.
        no2: NO2 concentration in µg/m³.
        o3: O3 concentration in µg/m³.
        so2: SO2 concentration in µg/m³.

    Returns:
        Integer AQI level in the closed range ``[1, AQI_MAX_LEVEL]``.
    """
    return max(
        _sub_index(pm2_5, AQI_BREAKPOINTS["pm2_5"]),
        _sub_index(pm10, AQI_BREAKPOINTS["pm10"]),
        _sub_index(no2, AQI_BREAKPOINTS["no2"]),
        _sub_index(o3, AQI_BREAKPOINTS["o3"]),
        _sub_index(so2, AQI_BREAKPOINTS["so2"]),
    )


def _jitter(value: float) -> float:
    """Apply Gaussian noise to a non-negative pollutant value.

    Args:
        value: Original pollutant concentration.

    Returns:
        A non-negative value perturbed by a Gaussian with standard deviation
        ``|value| * JITTER_FRAC``, rounded to two decimal places.
    """
    if value == 0.0:
        return 0.0
    noisy = random.gauss(value, abs(value) * JITTER_FRAC)
    return max(0.0, round(noisy, 2))


def expand_row(row: dict) -> list[dict]:
    """Expand a single hourly row into 60 jittered minute-level rows.

    Args:
        row: An hourly reading row matching :data:`PARQUET_SCHEMA`.

    Returns:
        A list of :data:`MINUTES_PER_HOUR` per-minute rows whose timestamps
        cover the hour starting at the row's hour boundary.
    """
    base_ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    base_ts = base_ts.replace(minute=0, second=0, microsecond=0)

    minutes = []
    for m in range(MINUTES_PER_HOUR):
        ts = base_ts + timedelta(minutes=m)
        co = _jitter(row.get("co") or 0.0)
        no = _jitter(row.get("no") or 0.0)
        no2 = _jitter(row.get("no2") or 0.0)
        o3 = _jitter(row.get("o3") or 0.0)
        so2 = _jitter(row.get("so2") or 0.0)
        pm2_5 = _jitter(row.get("pm2_5") or 0.0)
        pm10 = _jitter(row.get("pm10") or 0.0)
        nh3 = _jitter(row.get("nh3") or 0.0)

        minutes.append(
            {
                "sensor_id": row["sensor_id"],
                "station_name": row["station_name"],
                "city": row["city"],
                "region": row.get("region", ""),
                "country": row.get("country", "UA"),
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "timestamp": ts.isoformat(),
                "date": ts.strftime("%Y-%m-%d"),
                "aqi": compute_aqi(pm2_5, pm10, no2, o3, so2),
                "co": co,
                "no": no,
                "no2": no2,
                "o3": o3,
                "so2": so2,
                "pm2_5": pm2_5,
                "pm10": pm10,
                "nh3": nh3,
            }
        )
    return minutes


def make_client():
    """Build a boto3 S3 client pointed at the configured MinIO endpoint.

    Returns:
        A configured boto3 S3 client instance.
    """
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name=MINIO_REGION,
    )


def ensure_bucket(s3, bucket: str) -> None:
    """Ensure a bucket exists, creating it if necessary.

    Args:
        s3: A boto3 S3 client.
        bucket: Name of the bucket to ensure.

    Returns:
        None.
    """
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        print(f"Created bucket '{bucket}'")


def key_exists(s3, bucket: str, key: str) -> bool:
    """Check whether an object key exists in a bucket.

    Args:
        s3: A boto3 S3 client.
        bucket: Target bucket name.
        key: Object key to probe.

    Returns:
        ``True`` if the object exists, ``False`` otherwise.
    """
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def list_source_keys(s3) -> list[str]:
    """List all Parquet object keys in the source bucket.

    Args:
        s3: A boto3 S3 client.

    Returns:
        A list of object keys whose names end with ``.parquet``.
    """
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=SRC_BUCKET):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                keys.append(obj["Key"])
    return keys


def process_key(key: str) -> tuple[str, int]:
    """Expand one source Parquet file into the destination bucket.

    Args:
        key: Source object key inside :data:`SRC_BUCKET`.

    Returns:
        A two-tuple ``(key, rows_written)``. ``rows_written`` is ``0`` when
        the destination object already exists or the source had no rows.
    """
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

    table = pa.Table.from_pylist(expanded, schema=PARQUET_SCHEMA)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    s3.put_object(Bucket=DST_BUCKET, Key=key, Body=buf.getvalue())
    return (key, len(expanded))


def main() -> None:
    """Run the hourly-to-minutely expansion across the entire source bucket.

    Returns:
        None.
    """
    s3 = make_client()

    print(f"Source : s3://{SRC_BUCKET}")
    print(f"Dest   : s3://{DST_BUCKET}")
    print(f"Jitter : ±{JITTER_FRAC * 100:.0f}%  Workers: {WORKERS}")

    ensure_bucket(s3, DST_BUCKET)

    keys = list_source_keys(s3)
    if not keys:
        print(
            "No Parquet files found in source bucket — run historical_loader.py first."
        )
        sys.exit(1)

    print(
        f"Found {len(keys):,} source files — expanding each hourly row → "
        f"{MINUTES_PER_HOUR} minute rows\n"
    )

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
                print(
                    f"  [{i:>6}/{len(keys)}  {pct:5.1f}%]  "
                    f"written={done}  skipped={skipped}  rows≈{total_rows:,}"
                )

    print(f"\nDone.  {done} files written, {skipped} skipped (already existed).")
    print(f"Total minute-level rows: {total_rows:,}")
    if total_rows:
        rate_per_min = (
            total_rows
            / (HISTORY_PERIOD_DAYS * 24 * MINUTES_PER_HOUR)
            * MINUTES_PER_HOUR
        )
        print(
            f"Expected replay rate at REPLAY_SPEED={REPLAY_SPEED_DEFAULT}: "
            f"~{rate_per_min:,.0f} events/min"
        )


if __name__ == "__main__":
    main()
