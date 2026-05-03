"""
Air Quality Flink Stream Processor

  Kafka (air-quality-raw)
    -> Table API: 60-sec tumbling window aggregation per sensor
    -> DataStream: KeyedProcessFunction alert state machine (onset / recovery)
    -> Kafka (air-quality-aggregated)  +  JDBC -> TimescaleDB sensor_aggregates
    -> Kafka (air-quality-alerts)      +  psycopg2 -> TimescaleDB air_quality_alerts
"""
import json
import math
import os
import uuid
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.functions import KeyedProcessFunction, MapFunction, RuntimeContext
from pyflink.datastream.state import ValueStateDescriptor, ListStateDescriptor
from pyflink.common import Row
from pyflink.common.typeinfo import Types
from pyflink.table import StreamTableEnvironment

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP   = "broker:29092"
SOURCE_TOPIC      = "air-quality-raw"
AGG_TOPIC         = "air-quality-aggregated"
ALERTS_TOPIC      = "air-quality-alerts"
TIMESCALEDB_URL   = "jdbc:postgresql://timescaledb:5432/airquality"
TIMESCALEDB_USER  = "pipeline"
TIMESCALEDB_PASS  = "pipeline"

# ── alert thresholds ─────────────────────────────────────────────────────────
# Used as fallback when no historical baselines are available for a sensor.
FALLBACK_AQI_THRESHOLD  = 4     # OWM Poor or worse
FALLBACK_PM25_THRESHOLD = 25.0  # ug/m3

# Alert when value exceeds mean + Z_SCORE_THRESHOLD * std (dynamic mode)
Z_SCORE_THRESHOLD = 2.0

# Consecutive windows required to trigger / resolve an alert
ONSET_WINDOWS    = 3   # 3 bad windows (~3 min) before firing
RECOVERY_WINDOWS = 3   # 3 good windows (~3 min) before resolving

# ── history buffer: 72 windows × 60 s = ~72 min of context ──────────────────
HISTORY_SIZE = 72

# Checked in both the local src dir and the Docker volume mount path
BASELINES_FILE = Path(os.getenv(
    "BASELINES_FILE",
    str(Path(__file__).parent / "baselines" / "baselines.json"),
))

_SEVERITY = {1: "good", 2: "fair", 3: "moderate", 4: "poor", 5: "very_poor"}

class AirQualityAlertFunction(KeyedProcessFunction):
    """
    Keyed by sensor_id. Maintains two pieces of managed state:
      - ValueState : current alert status (normal / firing)
      - ListState  : rolling history buffer of recent window aggregates
    Alert detection (per sensor):
      - If historical baselines exist: Z-score on pm2_5 and aqi
        (alert when value > mean + Z_SCORE_THRESHOLD * std)
      - Fallback: fixed thresholds (FALLBACK_AQI_THRESHOLD / FALLBACK_PM25_THRESHOLD)

    Emits a JSON string only on onset and recovery state transitions.
    """

    def __init__(self, baselines: dict):
        self.baselines   = baselines
        self.alert_state = None
        self.history     = None

    def open(self, runtime_context: RuntimeContext):
        self.alert_state = runtime_context.get_state(
            ValueStateDescriptor("alert_status", Types.PICKLED_BYTE_ARRAY())
        )
        self.history = runtime_context.get_list_state(
            ListStateDescriptor("window_history", Types.PICKLED_BYTE_ARRAY())
        )


    def _is_elevated(self, sensor_id: str, avg_pm2_5: float, avg_aqi: float) -> bool:
        b = self.baselines.get(sensor_id)
        if b:
            pm25_b = b.get("pm2_5", {})
            aqi_b  = b.get("aqi",   {})
            if pm25_b.get("mean") is not None and pm25_b.get("std"):
                z_pm25 = (avg_pm2_5 - pm25_b["mean"]) / pm25_b["std"]
                z_aqi  = (avg_aqi   - aqi_b["mean"])  / aqi_b["std"] if aqi_b.get("std") else 0
                return z_pm25 > Z_SCORE_THRESHOLD or z_aqi > Z_SCORE_THRESHOLD
        return avg_aqi >= FALLBACK_AQI_THRESHOLD or avg_pm2_5 > FALLBACK_PM25_THRESHOLD

    @staticmethod
    def _trend(history: list) -> str:
        if len(history) < 4:
            return "stable"
        half   = len(history) // 2
        early  = sum(w["avg_pm2_5"] for w in history[:half]) / half
        recent = sum(w["avg_pm2_5"] for w in history[half:]) / (len(history) - half)
        if early == 0:
            return "stable"
        change = (recent - early) / early
        if change > 0.10:  return "worsening"
        if change < -0.10: return "improving"
        return "stable"

    @staticmethod
    def _make_alert(row, event_type: str, state: dict,
                    trend: str, peak_pm2_5: float, duration_min: int = 0) -> str:
        return json.dumps({
            "alert_id":            str(uuid.uuid4()),
            "sensor_id":           row["sensor_id"],
            "city":                row["city"],
            "latitude":            row["latitude"],
            "longitude":           row["longitude"],
            "event_type":          event_type,
            "duration_minutes":    duration_min,
            "consecutive_windows": state["windows_elevated"],
            "peak_pm2_5":          peak_pm2_5,
            "avg_aqi":             round(row["avg_aqi"], 3),
            "trend":               trend,
            "severity":            _SEVERITY.get(round(row["avg_aqi"]), "unknown"),
            "timestamp":           datetime.now(timezone.utc).isoformat(),
        })

    def process_element(self, row, ctx):
        state = self.alert_state.value() or {
            "status":           "normal",
            "onset_time":       None,
            "windows_elevated": 0,
            "windows_pending":  0,
            "windows_recovery": 0,
        }

        history = list(self.history.get())
        history.append({
            "avg_pm2_5": row["avg_pm2_5"],
            "max_pm2_5": row["max_pm2_5"],
            "avg_aqi":   row["avg_aqi"],
        })
        history = history[-HISTORY_SIZE:]
        self.history.update(history)

        is_elevated = self._is_elevated(row["sensor_id"], row["avg_pm2_5"], row["avg_aqi"])
        trend       = self._trend(history)
        peak_pm2_5  = max(w["max_pm2_5"] for w in history)

        if state["status"] == "normal":
            if is_elevated:
                state["windows_pending"] += 1
                if state["windows_pending"] >= ONSET_WINDOWS:
                    state.update({
                        "status":           "firing",
                        "onset_time":       datetime.now(timezone.utc).isoformat(),
                        "windows_elevated": state["windows_pending"],
                        "windows_pending":  0,
                        "windows_recovery": 0,
                    })
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
                        (datetime.now(timezone.utc) -
                         datetime.fromisoformat(state["onset_time"])).total_seconds() / 60
                    )
                    yield self._make_alert(row, "recovery", state, trend, peak_pm2_5, duration)
                    state = {
                        "status":           "normal",
                        "onset_time":       None,
                        "windows_elevated": 0,
                        "windows_pending":  0,
                        "windows_recovery": 0,
                    }

        self.alert_state.update(state)

def _create_source(t_env):
    t_env.execute_sql(f"""
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
            WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = '{SOURCE_TOPIC}',
            'properties.bootstrap.servers'  = '{KAFKA_BOOTSTRAP}',
            'properties.group.id'           = 'flink-processor',
            'scan.startup.mode'             = 'latest-offset',
            'format'                        = 'json',
            'json.fail-on-missing-field'    = 'false',
            'json.ignore-parse-errors'      = 'true'
        )
    """)


def _create_aggregated_kafka_sink(t_env):
    t_env.execute_sql(f"""
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
    """)


def _create_timescaledb_sink(t_env):
    t_env.execute_sql(f"""
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
    """)


_ALERT_ROW_TYPE = Types.ROW_NAMED(
    ["alert_id", "sensor_id", "city", "latitude", "longitude", "event_type",
     "duration_minutes", "consecutive_windows", "peak_pm2_5", "avg_aqi", "trend", "severity"],
    [Types.STRING(), Types.STRING(), Types.STRING(), Types.DOUBLE(), Types.DOUBLE(),
     Types.STRING(), Types.INT(), Types.INT(), Types.DOUBLE(), Types.DOUBLE(),
     Types.STRING(), Types.STRING()],
)


class ParseAlert(MapFunction):
    """Deserialises the alert JSON string emitted by AirQualityAlertFunction into a typed Row."""

    def map(self, json_str: str):
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


def _create_timescaledb_alerts_sink(t_env):
    t_env.execute_sql(f"""
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
    """)


def _create_alerts_sink(t_env):
    t_env.execute_sql(f"""
        CREATE TABLE alerts_sink (
            message STRING
        ) WITH (
            'connector'                    = 'kafka',
            'topic'                        = '{ALERTS_TOPIC}',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP}',
            'format'                       = 'raw'
        )
    """)

def _window_aggregation(t_env):
    """60-second tumbling window aggregation per sensor."""
    return t_env.sql_query("""
        SELECT
            TUMBLE_START(event_time, INTERVAL '60' SECOND) AS window_start,
            TUMBLE_END(event_time,   INTERVAL '60' SECOND) AS window_end,
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
            TUMBLE(event_time, INTERVAL '60' SECOND),
            sensor_id, city, station_name
    """)


def main():
    logger.info("Starting Air Quality Flink Stream Processor")

    env   = StreamExecutionEnvironment.get_execution_environment()
    t_env = StreamTableEnvironment.create(env)

    env.set_parallelism(1)
    t_env.get_config().set("execution.checkpointing.interval", "10s")
    t_env.get_config().set("execution.checkpointing.mode", "EXACTLY_ONCE")
    t_env.get_config().set("table.exec.source.idle-timeout", "5000")

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
    alert_json_stream = (
        aggregated_stream
        .key_by(lambda row: row["sensor_id"])
        .process(AirQualityAlertFunction(baselines), output_type=Types.STRING())
    )

    from pyflink.table.expressions import col
    alert_kafka_table = (
        t_env.from_data_stream(alert_json_stream)
        .select(col("f0").alias("message"))
    )

    alert_row_stream  = alert_json_stream.map(ParseAlert(), output_type=_ALERT_ROW_TYPE)
    alert_jdbc_table  = t_env.from_data_stream(alert_row_stream)

    stmt = t_env.create_statement_set()
    stmt.add_insert("aggregated_sink",        aggregated_table)
    stmt.add_insert("timescaledb_aggregates", aggregated_table)
    stmt.add_insert("alerts_sink",            alert_kafka_table)
    stmt.add_insert("timescaledb_alerts",     alert_jdbc_table)
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