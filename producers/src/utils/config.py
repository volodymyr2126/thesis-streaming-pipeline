"""Configuration for the air quality producer service."""
import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "air-quality-raw")

PRODUCER_MODE = os.getenv("PRODUCER_MODE", "replay")  # "replay" | "realtime"
OWM_API_KEY   = os.getenv("OWM_API_KEY", "")

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

