import os
from pathlib import Path

import pyarrow as pa

OWM_API_KEY = os.environ.get("OWM_API_KEY", "")

GEONAMES_URL = "https://download.geonames.org/export/dump/UA.zip"
OWM_URL = "https://api.openweathermap.org/data/2.5/air_pollution/history"
GEONAMES_REQUEST_TIMEOUT_SECONDS = 60
OWM_REQUEST_TIMEOUT_SECONDS = 30

DAYS_HISTORY = int(os.getenv("DAYS_HISTORY", "30"))
MIN_POPULATION = int(os.getenv("MIN_POPULATION", "10000"))

PER_STATION_SLEEP_SECONDS = 0.2

ADMIN1_TO_REGION = {
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

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "air-quality-historical")
MINIO_REGION = "us-east-1"

SRC_BUCKET = os.getenv("SRC_BUCKET", "air-quality-historical")
DST_BUCKET = os.getenv("DST_BUCKET", "air-quality-minutely")
JITTER_FRAC = float(os.getenv("JITTER_FRAC", "0.05"))
WORKERS = int(os.getenv("WORKERS", "8"))

MINUTES_PER_HOUR = 60
REPLAY_SPEED_DEFAULT = 60
HISTORY_PERIOD_DAYS = 31

REPO_ROOT = Path(__file__).parent.parent
BASELINES_OUT = Path(
    os.getenv(
        "BASELINES_OUT",
        str(REPO_ROOT / "flink-jobs" / "src" / "baselines" / "baselines.json"),
    )
)

POLLUTANTS = ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]

MIN_SAMPLES_FOR_STATS = 2
ROUND_DECIMALS = 4
MIN_STD = 0.1

AQI_BREAKPOINTS = {
    "pm2_5": [10, 20, 25, 50],
    "pm10": [20, 40, 50, 100],
    "no2": [40, 90, 120, 230],
    "o3": [60, 100, 130, 240],
    "so2": [100, 200, 350, 500],
}
AQI_MAX_LEVEL = 5

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("sensor_id", pa.string()),
        pa.field("station_name", pa.string()),
        pa.field("city", pa.string()),
        pa.field("region", pa.string()),
        pa.field("country", pa.string()),
        pa.field("latitude", pa.float64()),
        pa.field("longitude", pa.float64()),
        pa.field("timestamp", pa.string()),
        pa.field("date", pa.string()),
        pa.field("aqi", pa.int32()),
        pa.field("co", pa.float64()),
        pa.field("no", pa.float64()),
        pa.field("no2", pa.float64()),
        pa.field("o3", pa.float64()),
        pa.field("so2", pa.float64()),
        pa.field("pm2_5", pa.float64()),
        pa.field("pm10", pa.float64()),
        pa.field("nh3", pa.float64()),
    ]
)
