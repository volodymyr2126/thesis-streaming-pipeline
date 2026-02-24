-- ClickHouse Schema for Streaming Pipeline
-- This file is automatically executed when ClickHouse starts

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS analytics;

-- Use the analytics database
USE analytics;

-- Table for raw events (direct from Kafka)
CREATE TABLE IF NOT EXISTS events_raw (
    event_id String,
    timestamp DateTime64(3),
    user_id UInt32,
    event_type String,
    value UInt32,
    processing_time DateTime64(3) DEFAULT now64()
) ENGINE = MergeTree()
ORDER BY (timestamp, user_id)
PARTITION BY toYYYYMMDD(timestamp)
SETTINGS index_granularity = 8192;

-- Table for aggregated events (written via Kafka engine MV below)
CREATE TABLE IF NOT EXISTS events_aggregated (
    window_start DateTime64(3),
    window_end DateTime64(3),
    user_id UInt32,
    event_count UInt64,
    total_value UInt64,
    avg_value Float64,
    processing_time DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (window_start, user_id)
PARTITION BY toYYYYMM(window_start)
SETTINGS index_granularity = 8192;

-- Kafka engine table: reads aggregated-events topic written by Flink
CREATE TABLE IF NOT EXISTS events_aggregated_queue (
    window_start DateTime,
    window_end DateTime,
    user_id UInt32,
    event_count UInt64,
    total_value UInt64,
    avg_value Float64
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'broker:29092',
    kafka_topic_list = 'aggregated-events',
    kafka_group_name = 'clickhouse-aggregated-consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

-- Materialized view: moves rows from Kafka table into MergeTree
CREATE MATERIALIZED VIEW IF NOT EXISTS events_aggregated_mv
TO events_aggregated
AS SELECT
    window_start,
    window_end,
    user_id,
    event_count,
    total_value,
    avg_value
FROM events_aggregated_queue;

-- Materialized view for real-time event type distribution
CREATE MATERIALIZED VIEW IF NOT EXISTS event_type_stats
ENGINE = SummingMergeTree()
ORDER BY (event_type, hour)
POPULATE
AS SELECT
    event_type,
    toStartOfHour(timestamp) as hour,
    count() as event_count,
    sum(value) as total_value
FROM events_raw
GROUP BY event_type, hour;

-- Table for latency metrics (end-to-end tracking)
CREATE TABLE IF NOT EXISTS latency_metrics (
    measurement_time DateTime DEFAULT now(),
    producer_timestamp DateTime64(3),
    kafka_timestamp DateTime64(3),
    flink_timestamp DateTime64(3),
    clickhouse_timestamp DateTime64(3) DEFAULT now64(),
    end_to_end_ms Float64,
    user_id UInt32
) ENGINE = MergeTree()
ORDER BY measurement_time
PARTITION BY toYYYYMMDD(measurement_time)
SETTINGS index_granularity = 8192;

-- Create user with permissions (if needed)
-- ClickHouse alpine image uses 'default' user by default
