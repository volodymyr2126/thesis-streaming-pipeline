#!/bin/bash
# Get producer statistics
# Usage: ./stats.sh [--watch]

set -e

PRODUCER_URL="${PRODUCER_URL:-http://localhost:8000}"

if [ "$1" = "--watch" ] || [ "$1" = "-w" ]; then
    # Watch mode - refresh every 2 seconds
    echo "📊 Watching producer stats (Ctrl+C to exit)..."
    echo ""

    while true; do
        clear
        echo "📊 Producer Statistics - $(date '+%H:%M:%S')"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        RESPONSE=$(curl -s "$PRODUCER_URL/stats")

        # Parse and display
        echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
status = '🟢 Running' if data.get('is_running') else '⚪ Stopped'
print(f\"Status:         {status}\")
print(f\"Events sent:    {data.get('events_sent', 0):,}\")
print(f\"Events failed:  {data.get('events_failed', 0):,}\")
print(f\"Current rate:   {data.get('current_rate', 0):.2f} events/sec\")
print(f\"Duration:       {data.get('total_duration', 0):.2f} seconds\")
print(f\"Avg latency:    {data.get('avg_latency_ms', 0):.2f} ms\")
" 2>/dev/null || echo "$RESPONSE" | python3 -m json.tool

        echo ""
        echo "Press Ctrl+C to exit"
        sleep 2
    done
else
    # Single shot
    echo "📊 Producer Statistics"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    RESPONSE=$(curl -s "$PRODUCER_URL/stats")

    # Pretty print
    echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
status = '🟢 Running' if data.get('is_running') else '⚪ Stopped'
print(f\"Status:         {status}\")
print(f\"Events sent:    {data.get('events_sent', 0):,}\")
print(f\"Events failed:  {data.get('events_failed', 0):,}\")
print(f\"Current rate:   {data.get('current_rate', 0):.2f} events/sec\")
print(f\"Duration:       {data.get('total_duration', 0):.2f} seconds\")
print(f\"Avg latency:    {data.get('avg_latency_ms', 0):.2f} ms\")
" 2>/dev/null || echo "$RESPONSE" | python3 -m json.tool

    echo ""
    echo "💡 Tip: Run './stats.sh --watch' for continuous updates"
fi
