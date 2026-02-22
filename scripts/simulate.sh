#!/bin/bash
# Simulate event generation
# Usage: ./simulate.sh <rate> <num_events> [event_types]
# Example: ./simulate.sh 100 10000
# Example: ./simulate.sh 100 10000 "click,purchase"

set -e

PRODUCER_URL="${PRODUCER_URL:-http://localhost:8000}"

# Default values
RATE=${1:-10}
NUM_EVENTS=${2:-100}
EVENT_TYPES=${3:-}

# Build JSON payload
if [ -z "$EVENT_TYPES" ]; then
    # No event types specified - use all
    JSON_PAYLOAD="{\"rate\": $RATE, \"num_events\": $NUM_EVENTS}"
else
    # Convert comma-separated string to JSON array
    EVENT_TYPES_JSON=$(echo "$EVENT_TYPES" | sed 's/,/","/g' | sed 's/^/"/' | sed 's/$/"/')
    JSON_PAYLOAD="{\"rate\": $RATE, \"num_events\": $NUM_EVENTS, \"event_types\": [$EVENT_TYPES_JSON]}"
fi

echo "🚀 Starting simulation..."
echo "📊 Rate: $RATE events/sec"
echo "📈 Total events: $NUM_EVENTS"
echo "⏱️  Estimated duration: $((NUM_EVENTS / RATE)) seconds"
echo ""

# Send request
RESPONSE=$(curl -s -X POST "$PRODUCER_URL/simulate" \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD")

# Check if request was successful
if echo "$RESPONSE" | grep -q "\"status\":\"started\""; then
    echo "✅ Simulation started!"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
else
    echo "❌ Failed to start simulation:"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    exit 1
fi

echo ""
echo "💡 Tip: Run './stats.sh' to monitor progress"
echo "💡 Tip: Run './stop.sh' to stop simulation"
