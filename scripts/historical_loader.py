import io
import json
import math
import statistics
import time
import zipfile
from datetime import UTC, datetime, timedelta

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from botocore.exceptions import ClientError

from config import (
    ADMIN1_TO_REGION,
    BASELINES_OUT,
    DAYS_HISTORY,
    GEONAMES_REQUEST_TIMEOUT_SECONDS,
    GEONAMES_URL,
    MIN_POPULATION,
    MIN_SAMPLES_FOR_STATS,
    MIN_STD,
    MINIO_ACCESS,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET,
    OWM_API_KEY,
    OWM_REQUEST_TIMEOUT_SECONDS,
    OWM_URL,
    PARQUET_SCHEMA,
    PER_STATION_SLEEP_SECONDS,
    POLLUTANTS,
    ROUND_DECIMALS,
)


def fetch_geonames_stations() -> list[dict]:
    """Download the GeoNames Ukraine dump and yield virtual sensor stations.

    Filters the dump to populated places (``feature_class = 'P'``) in Ukraine
    whose recorded population is at least :data:`MIN_POPULATION`.

    Returns:
        A list of station dictionaries with ``sensor_id``, ``station_name``,
        ``city``, ``region``, ``country``, ``latitude`` and ``longitude`` keys,
        sorted alphabetically by city.

    Raises:
        requests.HTTPError: If the GeoNames dump cannot be downloaded.
    """
    print(f"Downloading GeoNames Ukraine dump from {GEONAMES_URL} ...")
    resp = requests.get(GEONAMES_URL, timeout=GEONAMES_REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()

    stations: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("UA.txt") as f:
            for raw in f:
                line = raw.decode("utf-8").rstrip("\n")
                cols = line.split("\t")
                if len(cols) < 15:
                    continue
                feature_class = cols[6]
                feature_code = cols[7]
                country_code = cols[8]
                if feature_class != "P" or country_code != "UA":
                    continue
                if feature_code in ("PPLX",):
                    continue
                try:
                    population = int(cols[14]) if cols[14] else 0
                except ValueError:
                    population = 0
                if population < MIN_POPULATION:
                    continue

                geonames_id = cols[0]
                name = cols[1]
                lat = float(cols[4])
                lon = float(cols[5])
                admin1 = cols[10]
                region = ADMIN1_TO_REGION.get(admin1, "")

                stations.append(
                    {
                        "sensor_id": f"ua_{geonames_id}",
                        "station_name": name,
                        "city": name,
                        "region": region,
                        "country": "UA",
                        "latitude": lat,
                        "longitude": lon,
                    }
                )

    stations.sort(key=lambda s: s["city"])
    print(
        f"Found {len(stations)} Ukrainian populated places "
        f"with population ≥ {MIN_POPULATION:,}"
    )
    return stations


def fetch_history(lat: float, lon: float) -> list[dict]:
    """Fetch hourly air-pollution history for a coordinate from OpenWeatherMap.

    Args:
        lat: Latitude of the sensor location.
        lon: Longitude of the sensor location.

    Returns:
        The raw ``list`` field of the OWM history response (may be empty).

    Raises:
        requests.HTTPError: If the OWM endpoint returns a non-2xx status.
    """
    end = int(datetime.now(UTC).timestamp())
    start = int((datetime.now(UTC) - timedelta(days=DAYS_HISTORY)).timestamp())

    resp = requests.get(
        OWM_URL,
        params={
            "lat": lat,
            "lon": lon,
            "start": start,
            "end": end,
            "appid": OWM_API_KEY,
        },
        timeout=OWM_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json().get("list", [])


def _stats(values: list[float]) -> dict:
    """Compute mean and standard deviation, dropping NaN/None inputs.

    Args:
        values: Raw numeric samples that may contain ``None`` or NaN.

    Returns:
        A dict ``{"mean": float | None, "std": float | None}``. Both fields
        are ``None`` when fewer than :data:`MIN_SAMPLES_FOR_STATS` valid
        samples are available; otherwise ``std`` is clamped to
        :data:`MIN_STD`.
    """
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if len(clean) < MIN_SAMPLES_FOR_STATS:
        return {"mean": None, "std": None}
    mean = statistics.mean(clean)
    std = statistics.stdev(clean)
    return {
        "mean": round(mean, ROUND_DECIMALS),
        "std": max(round(std, ROUND_DECIMALS), MIN_STD),
    }


def compute_baselines(readings: list[dict]) -> dict:
    """Compute per-pollutant baseline statistics for a sensor.

    Args:
        readings: OpenWeatherMap history entries for a single sensor.

    Returns:
        A mapping ``{pollutant: {"mean": ..., "std": ...}}`` covering every
        pollutant in :data:`POLLUTANTS` plus ``aqi``.
    """
    buckets: dict[str, list] = {p: [] for p in POLLUTANTS}
    aqi_vals = []

    for entry in readings:
        components = entry.get("components", {})
        for p in POLLUTANTS:
            v = components.get(p)
            if v is not None:
                buckets[p].append(v)
        aqi = entry.get("main", {}).get("aqi")
        if aqi is not None:
            aqi_vals.append(aqi)

    result = {p: _stats(buckets[p]) for p in POLLUTANTS}
    result["aqi"] = _stats(aqi_vals)
    return result


def _owm_to_row(entry: dict, station: dict) -> dict:
    """Convert an OWM history entry plus station metadata to a flat row.

    Args:
        entry: A single element from the OWM history ``list`` field.
        station: Station metadata dict with ``sensor_id`` and coordinates.

    Returns:
        A dictionary matching :data:`PARQUET_SCHEMA`.
    """
    c = entry.get("components", {})
    dt = datetime.fromtimestamp(entry["dt"], tz=UTC)
    return {
        "sensor_id": station["sensor_id"],
        "station_name": station["station_name"],
        "city": station["city"],
        "region": station.get("region", ""),
        "country": station["country"],
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "timestamp": dt.isoformat(),
        "date": dt.strftime("%Y-%m-%d"),
        "aqi": entry.get("main", {}).get("aqi"),
        "co": c.get("co"),
        "no": c.get("no"),
        "no2": c.get("no2"),
        "o3": c.get("o3"),
        "so2": c.get("so2"),
        "pm2_5": c.get("pm2_5"),
        "pm10": c.get("pm10"),
        "nh3": c.get("nh3"),
    }


def upload_parquet(s3, rows: list[dict], sensor_id: str, date: str) -> None:
    """Write a list of rows as a Parquet file to MinIO/S3.

    Args:
        s3: A boto3 S3 client.
        rows: Row dicts matching :data:`PARQUET_SCHEMA`.
        sensor_id: Sensor identifier used in the object key.
        date: ISO date (``YYYY-MM-DD``) used as a partition prefix.

    Returns:
        None.
    """
    table = pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    key = f"sensor_id={sensor_id}/date={date}/readings.parquet"
    s3.put_object(Bucket=MINIO_BUCKET, Key=key, Body=buf.getvalue())
    print(f"  uploaded s3://{MINIO_BUCKET}/{key}  ({len(rows)} rows)")


def ensure_bucket(s3) -> None:
    """Ensure the configured MinIO bucket exists, creating it if necessary.

    Args:
        s3: A boto3 S3 client.

    Returns:
        None.
    """
    try:
        s3.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=MINIO_BUCKET)
        print(f"Created bucket '{MINIO_BUCKET}'")


def bucket_has_data(s3) -> bool:
    """Return whether the configured bucket already contains any object.

    Args:
        s3: A boto3 S3 client.

    Returns:
        ``True`` if the bucket has at least one object, ``False`` otherwise.
    """
    resp = s3.list_objects_v2(Bucket=MINIO_BUCKET, MaxKeys=1)
    return resp.get("KeyCount", 0) > 0


def main() -> None:
    """Run the full historical-loader workflow.

    Downloads GeoNames, fetches OWM history per station, computes baselines,
    uploads per-day Parquet shards to MinIO and writes a station metadata
    file alongside.

    Returns:
        None.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name=MINIO_REGION,
    )
    ensure_bucket(s3)

    if bucket_has_data(s3):
        print(
            f"Bucket '{MINIO_BUCKET}' already contains data — skipping historical load."
        )
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
            print("  no data returned — skipping")
            continue

        print(f"  {len(raw)} hourly readings from OWM")

        all_baselines[sid] = compute_baselines(raw)

        by_date: dict[str, list] = {}
        for entry in raw:
            row = _owm_to_row(entry, station)
            date = row["date"]
            by_date.setdefault(date, []).append(row)

        for date, rows in by_date.items():
            upload_parquet(s3, rows, sid, date)

        time.sleep(PER_STATION_SLEEP_SECONDS)

    BASELINES_OUT.parent.mkdir(parents=True, exist_ok=True)
    BASELINES_OUT.write_text(json.dumps(all_baselines, indent=2))
    print(f"\nBaselines written → {BASELINES_OUT}  ({len(all_baselines)} stations)")

    station_meta = [
        {k: v for k, v in s.items()}
        for s in stations
        if s["sensor_id"] in all_baselines
    ]
    s3.put_object(
        Bucket=MINIO_BUCKET,
        Key="stations.json",
        Body=json.dumps(station_meta).encode(),
    )
    print(
        f"Station metadata written → s3://{MINIO_BUCKET}/stations.json  "
        f"({len(station_meta)} stations)"
    )


if __name__ == "__main__":
    main()
