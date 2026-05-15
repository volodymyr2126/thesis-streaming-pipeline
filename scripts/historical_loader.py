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
from botocore.exceptions import ClientError

# ── config ────────────────────────────────────────────────────────────────────
OWM_API_KEY = os.environ["OWM_API_KEY"]

GEONAMES_URL   = "https://download.geonames.org/export/dump/UA.zip"
OWM_URL        = "https://api.openweathermap.org/data/2.5/air_pollution/history"
DAYS_HISTORY   = int(os.getenv("DAYS_HISTORY", "30"))
MIN_POPULATION = int(os.getenv("MIN_POPULATION", "10000"))

_ADMIN1_TO_REGION = {
    "01": "Cherkasy Oblast",
    "02": "Chernihiv Oblast",
    "03": "Chernivtsi Oblast",
    "05": "Dnipropetrovsk Oblast",
    "06": "Donetsk Oblast",
    "07": "Ivano-Frankivsk Oblast",
    "08": "Kharkiv Oblast",
    "09": "Kherson Oblast",
    "10": "Khmelnytskyi Oblast",
    "11": "Kyiv Oblast",
    "12": "Kyiv City",
    "13": "Kirovohrad Oblast",
    "14": "Luhansk Oblast",
    "15": "Lviv Oblast",
    "16": "Mykolaiv Oblast",
    "17": "Odessa Oblast",
    "18": "Poltava Oblast",
    "19": "Rivne Oblast",
    "20": "Sumy Oblast",
    "21": "Ternopil Oblast",
    "22": "Vinnytsia Oblast",
    "23": "Volyn Oblast",
    "24": "Zakarpattia Oblast",
    "25": "Zaporizhzhia Oblast",
    "26": "Zhytomyr Oblast",
}

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT",  "http://localhost:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET   = os.getenv("MINIO_BUCKET",     "air-quality-historical")

REPO_ROOT    = Path(__file__).parent.parent
BASELINES_OUT = Path(os.getenv(
    "BASELINES_OUT",
    str(REPO_ROOT / "flink-jobs" / "src" / "baselines" / "baselines.json"),
))

POLLUTANTS = ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]


def fetch_geonames_stations() -> list[dict]:
    """Download the GeoNames Ukraine dump and return all populated places
    with population ≥ MIN_POPULATION as virtual sensor stations.

    GeoNames tab-separated columns (index):
      0  geonameid   6  feature_class   10 admin1_code   14 population
      1  name        7  feature_code    11 admin2_code
      4  latitude    8  country_code
      5  longitude
    """
    print(f"Downloading GeoNames Ukraine dump from {GEONAMES_URL} ...")
    resp = requests.get(GEONAMES_URL, timeout=60)
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
                feature_code  = cols[7]
                country_code  = cols[8]
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
                name        = cols[1]
                lat         = float(cols[4])
                lon         = float(cols[5])
                admin1      = cols[10]
                region      = _ADMIN1_TO_REGION.get(admin1, "")

                stations.append({
                    "sensor_id":    f"ua_{geonames_id}",
                    "station_name": name,
                    "city":         name,
                    "region":       region,
                    "country":      "UA",
                    "latitude":     lat,
                    "longitude":    lon,
                })

    stations.sort(key=lambda s: s["city"])
    print(f"Found {len(stations)} Ukrainian populated places "
          f"with population ≥ {MIN_POPULATION:,}")
    return stations



def fetch_history(lat: float, lon: float) -> list[dict]:
    end   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=DAYS_HISTORY)).timestamp())

    resp = requests.get(OWM_URL, params={
        "lat":   lat,
        "lon":   lon,
        "start": start,
        "end":   end,
        "appid": OWM_API_KEY,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json().get("list", [])



def _stats(values: list[float]) -> dict:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if len(clean) < 2:
        return {"mean": None, "std": None}
    mean = statistics.mean(clean)
    std  = statistics.stdev(clean)
    return {"mean": round(mean, 4), "std": max(round(std, 4), 0.1)}


def compute_baselines(readings: list[dict]) -> dict:
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



_PARQUET_SCHEMA = pa.schema([
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


def _owm_to_row(entry: dict, station: dict) -> dict:
    c  = entry.get("components", {})
    dt = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
    return {
        "sensor_id":    station["sensor_id"],
        "station_name": station["station_name"],
        "city":         station["city"],
        "region":       station.get("region", ""),
        "country":      station["country"],
        "latitude":     station["latitude"],
        "longitude":    station["longitude"],
        "timestamp":    dt.isoformat(),
        "date":         dt.strftime("%Y-%m-%d"),
        "aqi":          entry.get("main", {}).get("aqi"),
        "co":           c.get("co"),
        "no":           c.get("no"),
        "no2":          c.get("no2"),
        "o3":           c.get("o3"),
        "so2":          c.get("so2"),
        "pm2_5":        c.get("pm2_5"),
        "pm10":         c.get("pm10"),
        "nh3":          c.get("nh3"),
    }


def upload_parquet(s3, rows: list[dict], sensor_id: str, date: str):
    table = pa.Table.from_pylist(rows, schema=_PARQUET_SCHEMA)
    buf   = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    key = f"sensor_id={sensor_id}/date={date}/readings.parquet"
    s3.put_object(Bucket=MINIO_BUCKET, Key=key, Body=buf.getvalue())
    print(f"  uploaded s3://{MINIO_BUCKET}/{key}  ({len(rows)} rows)")


def ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=MINIO_BUCKET)
        print(f"Created bucket '{MINIO_BUCKET}'")


def bucket_has_data(s3) -> bool:
    resp = s3.list_objects_v2(Bucket=MINIO_BUCKET, MaxKeys=1)
    return resp.get("KeyCount", 0) > 0



def main():
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name="us-east-1",
    )
    ensure_bucket(s3)

    if bucket_has_data(s3):
        print(f"Bucket '{MINIO_BUCKET}' already contains data — skipping historical load.")
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
            row  = _owm_to_row(entry, station)
            date = row["date"]
            by_date.setdefault(date, []).append(row)

        for date, rows in by_date.items():
            upload_parquet(s3, rows, sid, date)

        time.sleep(0.2)

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
    print(f"Station metadata written → s3://{MINIO_BUCKET}/stations.json  ({len(station_meta)} stations)")


if __name__ == "__main__":
    main()
