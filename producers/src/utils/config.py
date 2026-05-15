import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "air-quality-raw")

PRODUCER_MODE = os.getenv("PRODUCER_MODE", "replay")
OWM_API_KEY = os.getenv("OWM_API_KEY", "")

PRODUCER_CONFIG = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "client.id": "air-quality-producer",
    "acks": "all",
    "retries": 3,
    "compression.type": "snappy",
    "linger.ms": 10,
    "batch.size": 16384,
    "enable.idempotence": True,
}

LATENCY_HISTORY_SIZE = 1000

KAFKA_TOPIC_AGGREGATED = "air-quality-aggregated"
KAFKA_TOPIC_ALERTS = "air-quality-alerts"

TOPIC_RAW_PARTITIONS = 3
TOPIC_AGG_PARTITIONS = 3
TOPIC_ALERTS_PARTITIONS = 1
TOPIC_REPLICATION_FACTOR = 1
ADMIN_LIST_TIMEOUT_SECONDS = 10

TOPIC_DEFAULTS = {
    "retention.ms": "604800000",
    "compression.type": "snappy",
    "max.message.bytes": "1048576",
}

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
MINIO_STATIONS_KEY = "stations.json"
REALTIME_HTTP_TIMEOUT_SECONDS = 10.0
REALTIME_PER_STATION_SLEEP_SECONDS = 1.0

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "air-quality-minutely")
MINIO_BUCKET_HISTORICAL = os.getenv("MINIO_BUCKET_HISTORICAL", "air-quality-historical")
MINIO_REGION = "us-east-1"

REPLAY_SPEED = float(os.getenv("REPLAY_SPEED", "1000"))
LOAD_WORKERS = int(os.getenv("LOAD_WORKERS", "16"))
SLEEP_PRECISION_SECONDS = 0.001

HOST = "0.0.0.0"
PORT = 8000
