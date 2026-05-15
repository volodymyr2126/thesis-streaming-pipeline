import json
import logging
import sys
import uuid
from datetime import UTC, datetime

from pyflink.common import Row
from pyflink.common.typeinfo import Types
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.functions import (
    KeyedProcessFunction,
    MapFunction,
    RuntimeContext,
)
from pyflink.datastream.state import ListStateDescriptor, ValueStateDescriptor
from pyflink.table import StreamTableEnvironment

from config import (
    AGG_TOPIC,
    ALERTS_TOPIC,
    BASELINES_FILE,
    CHECKPOINT_INTERVAL,
    CHECKPOINT_MODE,
    FALLBACK_AQI_THRESHOLD,
    FALLBACK_PM25_THRESHOLD,
    HISTORY_SIZE,
    KAFKA_BOOTSTRAP,
    KAFKA_GROUP_ID,
    MIN_HISTORY_FOR_TREND,
    ONSET_WINDOWS,
    PARALLELISM,
    RECOVERY_WINDOWS,
    SEVERITY,
    SOURCE_IDLE_TIMEOUT_MS,
    SOURCE_TOPIC,
    TIMESCALEDB_PASS,
    TIMESCALEDB_URL,
    TIMESCALEDB_USER,
    TREND_CHANGE_THRESHOLD,
    WATERMARK_SECONDS,
    WINDOW_SECONDS,
    Z_SCORE_THRESHOLD,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class AirQualityAlertFunction(KeyedProcessFunction):
    """Keyed Flink process function that emits onset and recovery alerts.

    The function is keyed by ``sensor_id`` and maintains two pieces of managed
    state: a value state holding the current alert status and a list state
    storing a rolling history of window aggregates. Alerts fire based on
    per-sensor Z-score baselines when available, falling back to fixed
    PM2.5 and AQI thresholds otherwise.
    """

    def __init__(self, baselines: dict):
        """Initialise the function with precomputed per-sensor baselines.

        Args:
            baselines: Mapping ``{sensor_id: {pollutant: {"mean": ...,
                "std": ...}}}`` produced by the historical loader.
        """
        self.baselines = baselines
        self.alert_state = None
        self.history = None

    def open(self, runtime_context: RuntimeContext):
        """Initialise managed state when the operator instance starts.

        Args:
            runtime_context: PyFlink runtime context bound to this operator.

        Returns:
            None.
        """
        self.alert_state = runtime_context.get_state(
            ValueStateDescriptor("alert_status", Types.PICKLED_BYTE_ARRAY())
        )
        self.history = runtime_context.get_list_state(
            ListStateDescriptor("window_history", Types.PICKLED_BYTE_ARRAY())
        )

    def _is_elevated(self, sensor_id: str, avg_pm2_5: float, avg_aqi: float) -> bool:
        """Decide whether a window aggregate should be flagged as elevated.

        Uses Z-score thresholds against precomputed baselines when available
        and falls back to fixed thresholds otherwise.

        Args:
            sensor_id: Identifier of the sensor.
            avg_pm2_5: Mean PM2.5 over the current window.
            avg_aqi: Mean AQI over the current window.

        Returns:
            ``True`` when the window is considered elevated.
        """
        b = self.baselines.get(sensor_id)
        if b:
            pm25_b = b.get("pm2_5", {})
            aqi_b = b.get("aqi", {})
            if pm25_b.get("mean") is not None and pm25_b.get("std"):
                z_pm25 = (avg_pm2_5 - pm25_b["mean"]) / pm25_b["std"]
                z_aqi = (
                    (avg_aqi - aqi_b["mean"]) / aqi_b["std"] if aqi_b.get("std") else 0
                )
                return z_pm25 > Z_SCORE_THRESHOLD or z_aqi > Z_SCORE_THRESHOLD
        return avg_aqi >= FALLBACK_AQI_THRESHOLD or avg_pm2_5 > FALLBACK_PM25_THRESHOLD

    @staticmethod
    def _trend(history: list) -> str:
        """Estimate whether PM2.5 is improving, worsening or stable.

        Args:
            history: Recent per-window aggregates with ``avg_pm2_5`` entries.

        Returns:
            One of ``"improving"``, ``"worsening"`` or ``"stable"``.
        """
        if len(history) < MIN_HISTORY_FOR_TREND:
            return "stable"
        half = len(history) // 2
        early = sum(w["avg_pm2_5"] for w in history[:half]) / half
        recent = sum(w["avg_pm2_5"] for w in history[half:]) / (len(history) - half)
        if early == 0:
            return "stable"
        change = (recent - early) / early
        if change > TREND_CHANGE_THRESHOLD:
            return "worsening"
        if change < -TREND_CHANGE_THRESHOLD:
            return "improving"
        return "stable"

    @staticmethod
    def _make_alert(
        row,
        event_type: str,
        state: dict,
        trend: str,
        peak_pm2_5: float,
        duration_min: int = 0,
    ) -> str:
        """Serialise an alert payload as a JSON string.

        Args:
            row: Window aggregate row at which the alert is emitted.
            event_type: ``"onset"`` or ``"recovery"``.
            state: Current per-sensor alert state.
            trend: Trend label produced by :meth:`_trend`.
            peak_pm2_5: Peak PM2.5 observed during the elevated period.
            duration_min: Duration of the event in minutes (recovery only).

        Returns:
            A JSON-encoded alert string.
        """
        return json.dumps(
            {
                "alert_id": str(uuid.uuid4()),
                "sensor_id": row["sensor_id"],
                "city": row["city"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "event_type": event_type,
                "duration_minutes": duration_min,
                "consecutive_windows": state["windows_elevated"],
                "peak_pm2_5": peak_pm2_5,
                "avg_aqi": round(row["avg_aqi"], 3),
                "trend": trend,
                "severity": SEVERITY.get(round(row["avg_aqi"]), "unknown"),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def process_element(self, row, ctx):
        """Process one window aggregate and yield alerts on transitions.

        Args:
            row: Incoming window aggregate row.
            ctx: Flink keyed process function context.

        Yields:
            JSON-encoded alert strings on onset or recovery transitions.
        """
        state = self.alert_state.value() or {
            "status": "normal",
            "onset_time": None,
            "windows_elevated": 0,
            "windows_pending": 0,
            "windows_recovery": 0,
        }

        history = list(self.history.get())
        history.append(
            {
                "avg_pm2_5": row["avg_pm2_5"],
                "max_pm2_5": row["max_pm2_5"],
                "avg_aqi": row["avg_aqi"],
            }
        )
        history = history[-HISTORY_SIZE:]
        self.history.update(history)

        is_elevated = self._is_elevated(
            row["sensor_id"], row["avg_pm2_5"], row["avg_aqi"]
        )
        trend = self._trend(history)
        peak_pm2_5 = max(w["max_pm2_5"] for w in history)

        if state["status"] == "normal":
            if is_elevated:
                state["windows_pending"] += 1
                if state["windows_pending"] >= ONSET_WINDOWS:
                    state.update(
                        {
                            "status": "firing",
                            "onset_time": datetime.now(UTC).isoformat(),
                            "windows_elevated": state["windows_pending"],
                            "windows_pending": 0,
                            "windows_recovery": 0,
                        }
                    )
                    yield self._make_alert(row, "onset", state, trend, peak_pm2_5)
            else:
                state["windows_pending"] = 0

        elif state["status"] == "firing":
            if is_elevated:
                state["windows_elevated"] += 1
                state["windows_recovery"] = 0
            else:
                state["windows_recovery"] += 1
                if state["windows_recovery"] >= RECOVERY_WINDOWS:
                    duration = int(
                        (
                            datetime.now(UTC)
                            - datetime.fromisoformat(state["onset_time"])
                        ).total_seconds()
                        / 60
                    )
                    yield self._make_alert(
                        row, "recovery", state, trend, peak_pm2_5, duration
                    )
                    state = {
                        "status": "normal",
                        "onset_time": None,
                        "windows_elevated": 0,
                        "windows_pending": 0,
                        "windows_recovery": 0,
                    }

        self.alert_state.update(state)


def _create_source(t_env) -> None:
    """Register the ``air_quality_raw`` source table backed by Kafka.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the table on.

    Returns:
        None.
    """
    t_env.execute_sql(
        f"""
        CREATE TABLE air_quality_raw (
            reading_id   STRING,
            sensor_id    STRING,
            station_name STRING,
            city         STRING,
            region       STRING,
            country      STRING,
            latitude     DOUBLE,
            longitude    DOUBLE,
            `timestamp`  STRING,
            co           DOUBLE,
            `no`         DOUBLE,
            no2          DOUBLE,
            o3           DOUBLE,
            so2          DOUBLE,
            pm2_5        DOUBLE,
            pm10         DOUBLE,
            nh3          DOUBLE,
            aqi          INT,
            is_anomaly   BOOLEAN,
            event_time AS TO_TIMESTAMP(REPLACE(SUBSTRING(`timestamp`, 1, 19), 'T', ' ')),
            WATERMARK FOR event_time AS event_time - INTERVAL '{WATERMARK_SECONDS}' SECOND
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = '{SOURCE_TOPIC}',
            'properties.bootstrap.servers'  = '{KAFKA_BOOTSTRAP}',
            'properties.group.id'           = '{KAFKA_GROUP_ID}',
            'scan.startup.mode'             = 'latest-offset',
            'format'                        = 'json',
            'json.fail-on-missing-field'    = 'false',
            'json.ignore-parse-errors'      = 'true'
        )
    """
    )


def _create_aggregated_kafka_sink(t_env) -> None:
    """Register the Kafka sink table for window-aggregated readings.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the table on.

    Returns:
        None.
    """
    t_env.execute_sql(
        f"""
        CREATE TABLE aggregated_sink (
            window_start  TIMESTAMP(3),
            window_end    TIMESTAMP(3),
            sensor_id     STRING,
            city          STRING,
            station_name  STRING,
            latitude      DOUBLE,
            longitude     DOUBLE,
            avg_pm2_5     DOUBLE,
            max_pm2_5     DOUBLE,
            avg_pm10      DOUBLE,
            avg_no2       DOUBLE,
            avg_o3        DOUBLE,
            avg_so2       DOUBLE,
            avg_aqi       DOUBLE,
            reading_count BIGINT
        ) WITH (
            'connector'                    = 'kafka',
            'topic'                        = '{AGG_TOPIC}',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP}',
            'format'                       = 'json',
            'json.timestamp-format.standard' = 'ISO-8601'
        )
    """
    )


def _create_timescaledb_sink(t_env) -> None:
    """Register the TimescaleDB sink table for aggregated readings.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the table on.

    Returns:
        None.
    """
    t_env.execute_sql(
        f"""
        CREATE TABLE timescaledb_aggregates (
            window_start  TIMESTAMP(3),
            window_end    TIMESTAMP(3),
            sensor_id     STRING,
            city          STRING,
            station_name  STRING,
            latitude      DOUBLE,
            longitude     DOUBLE,
            avg_pm2_5     DOUBLE,
            max_pm2_5     DOUBLE,
            avg_pm10      DOUBLE,
            avg_no2       DOUBLE,
            avg_o3        DOUBLE,
            avg_so2       DOUBLE,
            avg_aqi       DOUBLE,
            reading_count BIGINT
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = '{TIMESCALEDB_URL}',
            'table-name' = 'sensor_aggregates',
            'username'   = '{TIMESCALEDB_USER}',
            'password'   = '{TIMESCALEDB_PASS}',
            'driver'     = 'org.postgresql.Driver'
        )
    """
    )


_ALERT_ROW_TYPE = Types.ROW_NAMED(
    [
        "alert_id",
        "sensor_id",
        "city",
        "latitude",
        "longitude",
        "event_type",
        "duration_minutes",
        "consecutive_windows",
        "peak_pm2_5",
        "avg_aqi",
        "trend",
        "severity",
    ],
    [
        Types.STRING(),
        Types.STRING(),
        Types.STRING(),
        Types.DOUBLE(),
        Types.DOUBLE(),
        Types.STRING(),
        Types.INT(),
        Types.INT(),
        Types.DOUBLE(),
        Types.DOUBLE(),
        Types.STRING(),
        Types.STRING(),
    ],
)


class ParseAlert(MapFunction):
    """Deserialise alert JSON strings into typed Flink ``Row`` records."""

    def map(self, json_str: str):
        """Convert one alert JSON payload into a typed Row.

        Args:
            json_str: JSON-encoded alert produced by
                :class:`AirQualityAlertFunction`.

        Returns:
            A :class:`pyflink.common.Row` matching :data:`_ALERT_ROW_TYPE`.
        """
        a = json.loads(json_str)
        return Row(
            a.get("alert_id", ""),
            a.get("sensor_id", ""),
            a.get("city", ""),
            float(a.get("latitude") or 0.0),
            float(a.get("longitude") or 0.0),
            a.get("event_type", ""),
            int(a.get("duration_minutes") or 0),
            int(a.get("consecutive_windows") or 0),
            float(a.get("peak_pm2_5") or 0.0),
            float(a.get("avg_aqi") or 0.0),
            a.get("trend", ""),
            a.get("severity", ""),
        )


def _create_timescaledb_alerts_sink(t_env) -> None:
    """Register the TimescaleDB sink table for emitted alerts.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the table on.

    Returns:
        None.
    """
    t_env.execute_sql(
        f"""
        CREATE TABLE timescaledb_alerts (
            alert_id             STRING,
            sensor_id            STRING,
            city                 STRING,
            latitude             DOUBLE,
            longitude            DOUBLE,
            event_type           STRING,
            duration_minutes     INT,
            consecutive_windows  INT,
            peak_pm2_5           DOUBLE,
            avg_aqi              DOUBLE,
            trend                STRING,
            severity             STRING
        ) WITH (
            'connector'  = 'jdbc',
            'url'        = '{TIMESCALEDB_URL}',
            'table-name' = 'air_quality_alerts',
            'username'   = '{TIMESCALEDB_USER}',
            'password'   = '{TIMESCALEDB_PASS}',
            'driver'     = 'org.postgresql.Driver'
        )
    """
    )


def _create_alerts_sink(t_env) -> None:
    """Register the Kafka sink table for raw alert JSON payloads.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the table on.

    Returns:
        None.
    """
    t_env.execute_sql(
        f"""
        CREATE TABLE alerts_sink (
            message STRING
        ) WITH (
            'connector'                    = 'kafka',
            'topic'                        = '{ALERTS_TOPIC}',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP}',
            'format'                       = 'raw'
        )
    """
    )


def _window_aggregation(t_env):
    """Define the tumbling-window aggregation over the source table.

    Args:
        t_env: Flink ``StreamTableEnvironment`` to register the query on.

    Returns:
        A Flink ``Table`` representing the aggregated stream.
    """
    return t_env.sql_query(
        f"""
        SELECT
            TUMBLE_START(event_time, INTERVAL '{WINDOW_SECONDS}' SECOND) AS window_start,
            TUMBLE_END(event_time,   INTERVAL '{WINDOW_SECONDS}' SECOND) AS window_end,
            sensor_id,
            city,
            station_name,
            AVG(latitude)  AS latitude,
            AVG(longitude) AS longitude,
            AVG(pm2_5)     AS avg_pm2_5,
            MAX(pm2_5)     AS max_pm2_5,
            AVG(pm10)      AS avg_pm10,
            AVG(no2)       AS avg_no2,
            AVG(o3)        AS avg_o3,
            AVG(so2)       AS avg_so2,
            AVG(CAST(aqi AS DOUBLE)) AS avg_aqi,
            COUNT(*)       AS reading_count
        FROM air_quality_raw
        GROUP BY
            TUMBLE(event_time, INTERVAL '{WINDOW_SECONDS}' SECOND),
            sensor_id, city, station_name
    """
    )


def main() -> None:
    """Configure and submit the Flink stream-processing job.

    Returns:
        None.
    """
    logger.info("Starting Air Quality Flink Stream Processor")

    env = StreamExecutionEnvironment.get_execution_environment()
    t_env = StreamTableEnvironment.create(env)

    env.set_parallelism(PARALLELISM)
    t_env.get_config().set("execution.checkpointing.interval", CHECKPOINT_INTERVAL)
    t_env.get_config().set("execution.checkpointing.mode", CHECKPOINT_MODE)
    t_env.get_config().set("table.exec.source.idle-timeout", SOURCE_IDLE_TIMEOUT_MS)

    baselines: dict = {}
    if BASELINES_FILE.exists():
        baselines = json.loads(BASELINES_FILE.read_text())
        logger.info(f"Loaded historical baselines for {len(baselines)} sensors")
    else:
        logger.warning("baselines.json not found — using fixed thresholds as fallback")

    _create_source(t_env)
    _create_aggregated_kafka_sink(t_env)
    _create_timescaledb_sink(t_env)
    _create_alerts_sink(t_env)
    _create_timescaledb_alerts_sink(t_env)

    aggregated_table = _window_aggregation(t_env)

    aggregated_stream = t_env.to_data_stream(aggregated_table)
    alert_json_stream = aggregated_stream.key_by(lambda row: row["sensor_id"]).process(
        AirQualityAlertFunction(baselines), output_type=Types.STRING()
    )

    from pyflink.table.expressions import col

    alert_kafka_table = t_env.from_data_stream(alert_json_stream).select(
        col("f0").alias("message")
    )

    alert_row_stream = alert_json_stream.map(ParseAlert(), output_type=_ALERT_ROW_TYPE)
    alert_jdbc_table = t_env.from_data_stream(alert_row_stream)

    stmt = t_env.create_statement_set()
    stmt.add_insert("aggregated_sink", aggregated_table)
    stmt.add_insert("timescaledb_aggregates", aggregated_table)
    stmt.add_insert("alerts_sink", alert_kafka_table)
    stmt.add_insert("timescaledb_alerts", alert_jdbc_table)
    stmt.execute()

    logger.info("Flink job submitted")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        sys.exit(1)
