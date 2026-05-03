"""Real-time OWM air pollution fetcher.

Polls the OWM current air pollution API for all stations once per hour.
Rate: 1 req/s (≤60/min, within free tier). Full sweep of ~414 stations
takes ~7 minutes; the generator then sleeps until the next UTC hour boundary.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

import httpx

from producers.src.data.models import SensorReading
from producers.src.utils.config import OWM_API_KEY

logger = logging.getLogger(__name__)

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
MINIO_STATIONS_KEY = "stations.json"


def _load_stations_from_minio() -> list[dict]:
    import boto3
    import os
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        region_name="us-east-1",
    )
    bucket = os.getenv("MINIO_BUCKET_HISTORICAL", "air-quality-historical")
    try:
        obj = s3.get_object(Bucket=bucket, Key=MINIO_STATIONS_KEY)
        stations = json.loads(obj["Body"].read())
        logger.info(f"Loaded {len(stations)} stations from MinIO {bucket}/{MINIO_STATIONS_KEY}")
        return stations
    except ClientError as e:
        raise RuntimeError(
            f"Could not load stations.json from MinIO bucket '{bucket}': {e}. "
            "Re-run scripts/historical_loader.py to regenerate it."
        )


def _parse_reading(station: dict, data: dict) -> SensorReading:
    entry = data.get("list", [{}])[0]
    c = entry.get("components", {})
    now = datetime.now(timezone.utc)
    return SensorReading(
        reading_id=str(uuid.uuid4()),
        sensor_id=station["sensor_id"],
        station_name=station["station_name"],
        city=station["city"],
        region=station.get("region", ""),
        country=station.get("country", "UA"),
        latitude=station["latitude"],
        longitude=station["longitude"],
        timestamp=now.isoformat(),
        aqi=entry.get("main", {}).get("aqi"),
        co=c.get("co"),
        no=c.get("no"),
        no2=c.get("no2"),
        o3=c.get("o3"),
        so2=c.get("so2"),
        pm2_5=c.get("pm2_5"),
        pm10=c.get("pm10"),
        nh3=c.get("nh3"),
        is_anomaly=False,
    )


def _seconds_until_next_hour() -> float:
    now = datetime.now(timezone.utc)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()


async def realtime_stream():
    """Async generator yielding SensorReadings from live OWM API, once per hour."""
    if not OWM_API_KEY:
        raise RuntimeError("OWM_API_KEY is not set — cannot run in realtime mode")

    stations = _load_stations_from_minio()
    logger.info(f"Real-time mode: will poll {len(stations)} stations every hour")

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            cycle_start = datetime.now(timezone.utc)
            logger.info(f"Starting OWM poll cycle for {len(stations)} stations")
            success = 0

            for station in stations:
                try:
                    resp = await client.get(OWM_CURRENT_URL, params={
                        "lat":   station["latitude"],
                        "lon":   station["longitude"],
                        "appid": OWM_API_KEY,
                    })
                    resp.raise_for_status()
                    reading = _parse_reading(station, resp.json())
                    yield reading
                    success += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch {station['sensor_id']}: {e}")

                await asyncio.sleep(1.0)  # ≤60 req/min (OWM free tier limit)

            cycle_secs = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(f"Cycle complete: {success}/{len(stations)} stations in {cycle_secs:.0f}s")

            sleep_secs = _seconds_until_next_hour()
            logger.info(f"Sleeping {sleep_secs:.0f}s until next UTC hour boundary")
            await asyncio.sleep(sleep_secs)
