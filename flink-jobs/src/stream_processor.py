"""
Flink Stream Processing Job
Reads events from Kafka, performs windowed aggregations, writes to aggregated-events Kafka topic.
ClickHouse reads from that topic via the Kafka engine.
"""
import logging
import sys
from pyflink.table import (
    EnvironmentSettings,
    TableEnvironment,
)
from pyflink.table.expressions import col, lit
from pyflink.table.window import Tumble

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_kafka_source(t_env):
    """Create Kafka source table for raw events."""
    logger.info("Creating Kafka source table...")

    t_env.execute_sql("""
        CREATE TABLE kafka_source (
            event_id STRING,
            `timestamp` BIGINT,
            user_id INT,
            event_type STRING,
            event_value INT,
            event_time AS TO_TIMESTAMP_LTZ(`timestamp`, 3),
            WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'raw-events',
            'properties.bootstrap.servers' = 'broker:29092',
            'properties.group.id' = 'flink-processor',
            'scan.startup.mode' = 'latest-offset',
            'format' = 'json',
            'json.fail-on-missing-field' = 'false',
            'json.ignore-parse-errors' = 'true'
        )
    """)

    logger.info("Kafka source table created successfully")


def create_kafka_sink(t_env):
    """Create Kafka sink table for aggregated events.
    ClickHouse reads from this topic via the Kafka engine."""
    logger.info("Creating Kafka sink table...")

    t_env.execute_sql("""
        CREATE TABLE kafka_sink (
            window_start TIMESTAMP(3),
            window_end TIMESTAMP(3),
            user_id INT,
            event_count BIGINT,
            total_value BIGINT,
            avg_value DOUBLE
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'aggregated-events',
            'properties.bootstrap.servers' = 'broker:29092',
            'format' = 'json'
        )
    """)

    logger.info("Kafka sink table created successfully")


def process_stream(t_env):
    """Process stream with windowed aggregations."""
    logger.info("Starting stream processing...")

    events = t_env.from_path('kafka_source')

    result = events \
        .window(Tumble.over(lit(1).minutes).on(col('event_time')).alias('w')) \
        .group_by(col('w'), col('user_id')) \
        .select(
            col('w').start.alias('window_start'),
            col('w').end.alias('window_end'),
            col('user_id'),
            col('event_id').count.alias('event_count'),
            col('event_value').sum.alias('total_value'),
            col('event_value').avg.alias('avg_value')
        )

    result.execute_insert('kafka_sink')

    logger.info("Stream processing job submitted")


def main():
    """Main entry point for Flink job."""
    logger.info("=" * 60)
    logger.info("Starting Flink Stream Processing Job")
    logger.info("=" * 60)

    env_settings = EnvironmentSettings \
        .new_instance() \
        .in_streaming_mode() \
        .build()

    t_env = TableEnvironment.create(env_settings)

    t_env.get_config().set("parallelism.default", "1")
    t_env.get_config().set("execution.checkpointing.interval", "60s")
    t_env.get_config().set("execution.checkpointing.mode", "EXACTLY_ONCE")

    create_kafka_source(t_env)
    create_kafka_sink(t_env)
    process_stream(t_env)

    logger.info("Flink job is running.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Job interrupted by user")
    except Exception as e:
        logger.error(f"Job failed with error: {e}", exc_info=True)
        sys.exit(1)