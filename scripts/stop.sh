#!/bin/bash
# Stop current simulation
# Usage: ./stop.sh

set -e

PRODUCER_URL="${PRODUCER_URL:-http://localhost:8000}"

echo "🛑 Stopping simulation..."

RESPONSE=$(curl -s -X POST "$PRODUCER_URL/stop")

# Check if request was successful
if echo "$RESPONSE" | grep -q "\"status\":\"stopped\""; then
    echo "✅ Simulation stopped!"
    echo ""
    echo "📊 Final Statistics:"
    echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
stats = data.get('final_stats', {})
print(f\"  Events sent:    {stats.get('events_sent', 0):,}\")
print(f\"  Events failed:  {stats.get('events_failed', 0):,}\")
print(f\"  Total duration: {stats.get('total_duration', 0):.2f} seconds\")
print(f\"  Avg rate:       {stats.get('current_rate', 0):.2f} events/sec\")
print(f\"  Avg latency:    {stats.get('avg_latency_ms', 0):.2f} ms\")
" 2>/dev/null || echo "$RESPONSE" | python3 -m json.tool
else
    echo "⚠️  Response:"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
fi
