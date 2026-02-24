#!/bin/bash
# Query ClickHouse database
# Usage: ./clickhouse-query.sh "SELECT * FROM events_aggregated LIMIT 10"

set -e

QUERY=${1:-"SELECT count() FROM events_aggregated"}

echo "📊 Querying ClickHouse..."
echo "Query: $QUERY"
echo ""

docker exec clickhouse clickhouse-client \
    --query="$QUERY" \
    --format=PrettyCompact

echo ""
echo "💡 Tip: Use different formats: --format=JSON, --format=CSV, --format=TabSeparated"
