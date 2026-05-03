"""Kafka topic management."""
import logging
from confluent_kafka.admin import AdminClient, NewTopic
from producers.src.utils.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC

logger = logging.getLogger(__name__)

_TOPIC_DEFAULTS = {
    "retention.ms": "604800000",
    "compression.type": "snappy",
    "max.message.bytes": "1048576",
}


def create_topics_if_not_exist():
    admin_client = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

    topics = [
        NewTopic(KAFKA_TOPIC,              num_partitions=3, replication_factor=1, config=_TOPIC_DEFAULTS),
        NewTopic("air-quality-aggregated", num_partitions=3, replication_factor=1, config=_TOPIC_DEFAULTS),
        NewTopic("air-quality-alerts",     num_partitions=1, replication_factor=1, config=_TOPIC_DEFAULTS),
    ]

    metadata = admin_client.list_topics(timeout=10)
    existing = set(metadata.topics.keys())
    to_create = [t for t in topics if t.topic not in existing]

    if not to_create:
        logger.info("All Kafka topics already exist")
        return

    futures = admin_client.create_topics(to_create)
    for name, future in futures.items():
        try:
            future.result()
            logger.info(f"Created topic '{name}'")
        except Exception as e:
            logger.error(f"Failed to create topic '{name}': {e}")
            raise


def get_topic_info() -> dict:
    admin_client = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    metadata = admin_client.list_topics(timeout=10)
    result = {}
    for name in (KAFKA_TOPIC, "air-quality-aggregated", "air-quality-alerts"):
        if name in metadata.topics:
            result[name] = {"partitions": len(metadata.topics[name].partitions)}
    return result