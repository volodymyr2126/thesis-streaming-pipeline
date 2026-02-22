"""Kafka admin utilities for topic management."""
import logging
from confluent_kafka.admin import AdminClient, NewTopic
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC

logger = logging.getLogger(__name__)


def create_topics_if_not_exist():
    """Create Kafka topics if they don't exist."""
    admin_client = AdminClient({
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS
    })

    # Define topic configurations
    topics = [
        NewTopic(
            topic=KAFKA_TOPIC,
            num_partitions=3,  # 3 partitions for parallelism
            replication_factor=1,  # 1 for local dev (3 for production)
            config={
                'retention.ms': '604800000',  # 7 days in milliseconds
                'compression.type': 'snappy',  # Enable compression
                'max.message.bytes': '1048576',  # 1MB max message size
            }
        )
    ]

    # Get existing topics
    metadata = admin_client.list_topics(timeout=10)
    existing_topics = set(metadata.topics.keys())

    # Filter out topics that already exist
    topics_to_create = [t for t in topics if t.topic not in existing_topics]

    if not topics_to_create:
        logger.info(f"Topic '{KAFKA_TOPIC}' already exists")
        return

    # Create topics
    futures = admin_client.create_topics(topics_to_create)

    # Wait for topic creation
    for topic_name, future in futures.items():
        try:
            future.result()  # Block until topic is created
            logger.info(f"Topic '{topic_name}' created successfully with 3 partitions")
        except Exception as e:
            logger.error(f"Failed to create topic '{topic_name}': {e}")
            raise


def get_topic_info():
    """Get information about the topic."""
    admin_client = AdminClient({
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS
    })

    metadata = admin_client.list_topics(timeout=10)

    if KAFKA_TOPIC not in metadata.topics:
        return None

    topic_metadata = metadata.topics[KAFKA_TOPIC]

    return {
        'topic': KAFKA_TOPIC,
        'partitions': len(topic_metadata.partitions),
        'partition_details': [
            {
                'id': p.id,
                'leader': p.leader,
                'replicas': p.replicas,
                'isrs': p.isrs
            }
            for p in topic_metadata.partitions.values()
        ]
    }
