#!/bin/bash
# Clear all messages from Kafka topic
# Usage: ./clear-topic.sh [topic_name]

set -e

TOPIC_NAME=${1:-raw-events}
KAFKA_CONTAINER=${KAFKA_CONTAINER:-broker}

echo "🗑️  Clearing topic: $TOPIC_NAME"
echo ""

# Delete the topic
echo "1️⃣  Deleting topic..."
docker exec $KAFKA_CONTAINER kafka-topics \
    --bootstrap-server localhost:9092 \
    --delete \
    --topic $TOPIC_NAME 2>/dev/null || echo "   (topic may not exist)"

# Wait a moment for deletion
sleep 2

# Recreate the topic with same configuration
echo "2️⃣  Recreating topic with 3 partitions..."
docker exec $KAFKA_CONTAINER kafka-topics \
    --bootstrap-server localhost:9092 \
    --create \
    --topic $TOPIC_NAME \
    --partitions 3 \
    --replication-factor 1 \
    --config retention.ms=604800000 \
    --config compression.type=snappy \
    --config max.message.bytes=1048576 \
    --if-not-exists

echo ""
echo "✅ Topic cleared and recreated!"
echo ""

# Show topic details
echo "📋 Topic details:"
docker exec $KAFKA_CONTAINER kafka-topics \
    --bootstrap-server localhost:9092 \
    --describe \
    --topic $TOPIC_NAME

echo ""
echo "💡 Tip: Messages are completely removed, offsets reset to 0"
