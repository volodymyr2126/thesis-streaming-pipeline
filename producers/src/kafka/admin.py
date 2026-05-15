import logging

from confluent_kafka.admin import AdminClient, NewTopic

from producers.src.utils.config import (
    ADMIN_LIST_TIMEOUT_SECONDS,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC,
    KAFKA_TOPIC_AGGREGATED,
    KAFKA_TOPIC_ALERTS,
    TOPIC_AGG_PARTITIONS,
    TOPIC_ALERTS_PARTITIONS,
    TOPIC_DEFAULTS,
    TOPIC_RAW_PARTITIONS,
    TOPIC_REPLICATION_FACTOR,
)

logger = logging.getLogger(__name__)


def create_topics_if_not_exist() -> None:
    """Create the pipeline's Kafka topics if they are not already present.

    Returns:
        None.

    Raises:
        Exception: Re-raises the first failure from any topic creation future.
    """
    admin_client = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

    topics = [
        NewTopic(
            KAFKA_TOPIC,
            num_partitions=TOPIC_RAW_PARTITIONS,
            replication_factor=TOPIC_REPLICATION_FACTOR,
            config=TOPIC_DEFAULTS,
        ),
        NewTopic(
            KAFKA_TOPIC_AGGREGATED,
            num_partitions=TOPIC_AGG_PARTITIONS,
            replication_factor=TOPIC_REPLICATION_FACTOR,
            config=TOPIC_DEFAULTS,
        ),
        NewTopic(
            KAFKA_TOPIC_ALERTS,
            num_partitions=TOPIC_ALERTS_PARTITIONS,
            replication_factor=TOPIC_REPLICATION_FACTOR,
            config=TOPIC_DEFAULTS,
        ),
    ]

    metadata = admin_client.list_topics(timeout=ADMIN_LIST_TIMEOUT_SECONDS)
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
    """Return partition counts for the pipeline's Kafka topics.

    Returns:
        A mapping ``{topic_name: {"partitions": int}}`` covering only the
        pipeline topics that currently exist in the broker.
    """
    admin_client = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    metadata = admin_client.list_topics(timeout=ADMIN_LIST_TIMEOUT_SECONDS)
    result = {}
    for name in (KAFKA_TOPIC, KAFKA_TOPIC_AGGREGATED, KAFKA_TOPIC_ALERTS):
        if name in metadata.topics:
            result[name] = {"partitions": len(metadata.topics[name].partitions)}
    return result
