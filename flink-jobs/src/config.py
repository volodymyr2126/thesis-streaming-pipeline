import os
from pathlib import Path

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "broker:29092")
SOURCE_TOPIC = "air-quality-raw"
AGG_TOPIC = "air-quality-aggregated"
ALERTS_TOPIC = "air-quality-alerts"

TIMESCALEDB_URL = os.getenv(
    "TIMESCALEDB_URL", "jdbc:postgresql://timescaledb:5432/airquality"
)
TIMESCALEDB_USER = os.getenv("TIMESCALEDB_USER", "pipeline")
TIMESCALEDB_PASS = os.getenv("TIMESCALEDB_PASS", "pipeline")

FALLBACK_AQI_THRESHOLD = 4
FALLBACK_PM25_THRESHOLD = 25.0
Z_SCORE_THRESHOLD = 2.0

ONSET_WINDOWS = 10
RECOVERY_WINDOWS = 10
HISTORY_SIZE = 72

TREND_CHANGE_THRESHOLD = 0.10
MIN_HISTORY_FOR_TREND = 4

WINDOW_SECONDS = 60
WATERMARK_SECONDS = 5
SOURCE_IDLE_TIMEOUT_MS = "5000"
CHECKPOINT_INTERVAL = "10s"
CHECKPOINT_MODE = "EXACTLY_ONCE"
PARALLELISM = 1

KAFKA_GROUP_ID = "flink-processor"

BASELINES_FILE = Path(
    os.getenv(
        "BASELINES_FILE",
        str(Path(__file__).parent / "baselines" / "baselines.json"),
    )
)

SEVERITY = {1: "good", 2: "fair", 3: "moderate", 4: "poor", 5: "very_poor"}
