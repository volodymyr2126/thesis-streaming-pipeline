#!/bin/bash
# Check Flink job status
# Usage: ./flink-status.sh

set -e

FLINK_URL="${FLINK_URL:-http://localhost:8081}"

echo "📊 Flink Cluster Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if Flink is reachable
if ! curl -s "$FLINK_URL/overview" > /dev/null 2>&1; then
    echo "❌ Flink JobManager not reachable at $FLINK_URL"
    echo "💡 Is Flink running? Try: docker compose up -d flink-jobmanager flink-taskmanager"
    exit 1
fi

# Get overview
echo "🖥️  JobManager: http://localhost:8081"
echo ""

# Get jobs
echo "📋 Running Jobs:"
JOBS=$(curl -s "$FLINK_URL/jobs" | python3 -c "
import sys, json
data = json.load(sys.stdin)
jobs = data.get('jobs', [])
if not jobs:
    print('  No jobs running')
else:
    for job in jobs:
        status_icon = '🟢' if job['status'] == 'RUNNING' else '🔴'
        print(f\"  {status_icon} {job['id']} - {job['status']}\")
" 2>/dev/null || echo "  Unable to parse jobs")

echo ""

# Get taskmanagers
echo "🔧 TaskManagers:"
TMS=$(curl -s "$FLINK_URL/taskmanagers" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tms = data.get('taskmanagers', [])
if not tms:
    print('  No TaskManagers registered')
else:
    for tm in tms:
        print(f\"  ✓ {tm['id']} - {tm.get('slotsNumber', 0)} slots\")
" 2>/dev/null || echo "  Unable to parse taskmanagers")

echo ""
echo "💡 View detailed metrics: $FLINK_URL"
echo "💡 View job details: $FLINK_URL/#/job/running"
