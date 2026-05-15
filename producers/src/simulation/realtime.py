import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

import boto3
import httpx
from botocore.exceptions import ClientError

from producers.src.data.models import SensorReading
from producers.src.utils.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET_HISTORICAL,
    MINIO_REGION,
    MINIO_SECRET_KEY,
    MINIO_STATIONS_KEY,
    OWM_API_KEY,
    OWM_CURRENT_URL,
    REALTIME_HTTP_TIMEOUT_SECONDS,
    REALTIME_PER_STATION_SLEEP_SECONDS,
)

logger = logging.getLogger(__name__)


def _load_stations_from_minio() -> list[dict]:
    """Fetch the station metadata JSON written by the historical loader.

    Returns:
        A list of station metadata dictionaries.

    Raises:
        RuntimeError: If the stations object cannot be read from MinIO.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name=MINIO_REGION,
    )
    bucket = MINIO_BUCKET_HISTORICAL
    try:
        obj = s3.get_object(Bucket=bucket, Key=MINIO_STATIONS_KEY)
        stations = json.loads(obj["Body"].read())
        logger.info(
            f"Loaded {len(stations)} stations from MinIO {bucket}/{MINIO_STATIONS_KEY}"
        )
        return stations
    except ClientError as e:
        raise RuntimeError(
            f"Could not load stations.json from MinIO bucket '{bucket}': {e}. "
            "Re-run scripts/historical_loader.py to regenerate it."
        ) from e


def _parse_reading(station: dict, data: dict) -> SensorReading:
    """Build a :class:`SensorReading` from an OWM ``air_pollution`` response.

    Args:
        station: Station metadata dict.
        data: Parsed JSON body returned by the OWM API.

    Returns:
        A populated :class:`SensorReading` instance.
    """
    entry = data.get("list", [{}])[0]
    c = entry.get("components", {})
    now = datetime.now(UTC)
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
    """Compute the number of seconds remaining until the next UTC hour.

    Returns:
        Seconds until the next ``HH:00:00`` UTC boundary.
    """
    now = datetime.now(UTC)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()


async def realtime_stream():
    """Yield live :class:`SensorReading` records polled once per hour from OWM.

    Yields:
        :class:`SensorReading` instances, one per station per polling cycle.

    Raises:
        RuntimeError: If ``OWM_API_KEY`` is not configured.
    """
    if not OWM_API_KEY:
        raise RuntimeError("OWM_API_KEY is not set — cannot run in realtime mode")

    stations = _load_stations_from_minio()
    logger.info(f"Real-time mode: will poll {len(stations)} stations every hour")

    async with httpx.AsyncClient(timeout=REALTIME_HTTP_TIMEOUT_SECONDS) as client:
        while True:
            cycle_start = datetime.now(UTC)
            logger.info(f"Starting OWM poll cycle for {len(stations)} stations")
            success = 0

            for station in stations:
                try:
                    resp = await client.get(
                        OWM_CURRENT_URL,
                        params={
                            "lat": station["latitude"],
                            "lon": station["longitude"],
                            "appid": OWM_API_KEY,
                        },
                    )
                    resp.raise_for_status()
                    reading = _parse_reading(station, resp.json())
                    yield reading
                    success += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch {station['sensor_id']}: {e}")

                await asyncio.sleep(REALTIME_PER_STATION_SLEEP_SECONDS)

            cycle_secs = (datetime.now(UTC) - cycle_start).total_seconds()
            logger.info(
                f"Cycle complete: {success}/{len(stations)} stations "
                f"in {cycle_secs:.0f}s"
            )

            sleep_secs = _seconds_until_next_hour()
            logger.info(f"Sleeping {sleep_secs:.0f}s until next UTC hour boundary")
            await asyncio.sleep(sleep_secs)
