"""Configuration for the event producer service."""
import os
from typing import List

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "raw-events")

# Producer Configuration
PRODUCER_CONFIG = {
    "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
    "client.id": "event-producer",
    "acks": "all",  # Wait for all replicas to acknowledge
    "retries": 3,
    "compression.type": "snappy",
    "linger.ms": 10,  # Batch messages for 10ms
    "batch.size": 16384,  # 16KB batches
    "enable.idempotence": True,  # Exactly-once semantics
}

# Event Generation Configuration
DEFAULT_EVENT_RATE = int(os.getenv("DEFAULT_EVENT_RATE", "10"))  # events per second
MAX_EVENT_RATE = int(os.getenv("MAX_EVENT_RATE", "10000"))  # safety limit

# Event Types
EVENT_TYPES: List[str] = ["click", "view", "purchase", "signup", "logout"]

# User ID range
MIN_USER_ID = 1
MAX_USER_ID = 1000

# Value range (for numeric metrics)
MIN_VALUE = 1
MAX_VALUE = 1000
