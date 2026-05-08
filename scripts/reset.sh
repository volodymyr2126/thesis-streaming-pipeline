#!/usr/bin/env bash
# Reset all pipeline state for a clean run.
# Safe to run whether the stack is up or down.
# After completion the stack is fully stopped — run `docker compose up -d` to start fresh.
set -euo pipefail

COMPOSE="docker compose"

echo "==> Bringing down the full stack..."
$COMPOSE down --remove-orphans 2>/dev/null || true

echo "==> Starting only data services..."
$COMPOSE up -d kafka timescaledb

echo -n "    Waiting for Kafka"
until $COMPOSE exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092 >/dev/null 2>&1; do
  echo -n "."; sleep 3
done
echo " ready"

echo -n "    Waiting for TimescaleDB"
until $COMPOSE exec -T timescaledb pg_isready -U pipeline -d airquality >/dev/null 2>&1; do
  echo -n "."; sleep 2
done
echo " ready"


echo "==> Clearing TimescaleDB tables..."
$COMPOSE exec -T timescaledb psql -U pipeline -d airquality <<'SQL'
TRUNCATE TABLE sensor_aggregates;
TRUNCATE TABLE air_quality_alerts;
SQL

echo "==> Purging Kafka topics..."
TOPICS="air-quality-raw air-quality-aggregated air-quality-alerts"

for topic in $TOPICS; do
  $COMPOSE exec -T kafka kafka-configs \
    --bootstrap-server localhost:9092 \
    --entity-type topics --entity-name "$topic" \
    --alter --add-config retention.ms=1000 2>/dev/null || true
done

echo -n "    Waiting for segments to expire"
sleep 8
echo " done"

for topic in $TOPICS; do
  $COMPOSE exec -T kafka kafka-configs \
    --bootstrap-server localhost:9092 \
    --entity-type topics --entity-name "$topic" \
    --alter --delete-config retention.ms 2>/dev/null || true
done

echo "==> Clearing MinIO historical data..."
#$COMPOSE exec -T minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1 || true
#$COMPOSE exec -T minio mc rm --recursive --force local/air-quality-historical 2>/dev/null || true

echo "==> Clearing baselines from shared volume..."
$COMPOSE run --rm --no-deps \
  -v flink_baselines:/baselines \
  --entrypoint sh \
  flink-jobmanager -c "rm -f /baselines/baselines.json"

echo "==> Stopping data services..."
$COMPOSE down

echo ""
echo "Done. Run next:"
echo "  docker compose run --rm historical-loader   # reload historical data"
echo "  docker compose up -d                        # start the pipeline"
