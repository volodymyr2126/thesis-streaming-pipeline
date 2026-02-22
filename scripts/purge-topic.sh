#!/bin/bash
# Purge messages from Kafka topic (without deleting topic)
# Usage: ./purge-topic.sh [topic_name]

set -e

TOPIC_NAME=${1:-raw-events}
KAFKA_CONTAINER=${KAFKA_CONTAINER:-broker}

echo "🧹 Purging messages from topic: $TOPIC_NAME"
echo ""

# Method: Set retention to 1ms, wait, then restore to 7 days
echo "1️⃣  Setting retention to 1ms (messages will expire immediately)..."
docker exec $KAFKA_CONTAINER kafka-configs \
    --bootstrap-server localhost:9092 \
    --alter \
    --entity-type topics \
    --entity-name $TOPIC_NAME \
    --add-config retention.ms=1

echo "2️⃣  Waiting 10 seconds for messages to expire..."
sleep 10

echo "3️⃣  Restoring retention to 7 days..."
docker exec $KAFKA_CONTAINER kafka-configs \
    --bootstrap-server localhost:9092 \
    --alter \
    --entity-type topics \
    --entity-name $TOPIC_NAME \
    --add-config retention.ms=604800000

echo ""
echo "✅ Topic purged!"
echo ""
echo "📋 Note: Topic offsets are preserved, only messages deleted"
echo "💡 Tip: Use ./clear-topic.sh if you want to reset offsets too"
