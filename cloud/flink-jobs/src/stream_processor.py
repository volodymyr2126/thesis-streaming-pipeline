"""
Air Quality Flink Stream Processor — AWS Edition

  Kafka/MSK (air-quality-raw)
    -> Table API: 60-sec tumbling window aggregation per sensor
    -> DataStream: KeyedProcessFunction alert state machine (onset / recovery)
    -> Kafka (air-quality-aggregated)  +  psycopg2 -> TimescaleDB sensor_aggregates
    -> Kafka (air-quality-alerts)      +  psycopg2 -> TimescaleDB air_quality_alerts
"""
import json
import os
import uuid
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.functions import KeyedProcessFunction, RuntimeContext, MapFunction
from pyflink.datastream.state import ValueStateDescriptor, ListStateDescriptor
from pyflink.common.typeinfo import Types
from pyflink.table import StreamTableEnvironment

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── alert thresholds ─────────────────────────────────────────────────────────
FALLBACK_AQI_THRESHOLD  = 4
FALLBACK_PM25_THRESHOLD = 25.0
Z_SCORE_THRESHOLD       = 2.0
ONSET_WINDOWS           = 10
RECOVERY_WINDOWS        = 10
HISTORY_SIZE            = 72

_SEVERITY = {1: "good", 2: "fair", 3: "moderate", 4: "poor", 5: "very_poor"}


def _load_app_properties() -> dict:
    """Read config from /etc/flink/application_properties.json (Managed Flink)
    with OS environment variables taking precedence."""
    props: dict = {}

    props_file = "/etc/flink/application_properties.json"
    if os.path.isfile(props_file):
        with open(props_file) as f:
            for group in json.load(f):
                if group.get("PropertyGroupId") == "FlinkApplicationProperties":
                    props.update(group.get("PropertyMap", {}))

    for key in [
        "KAFKA_BOOTSTRAP", "AWS_REGION",
        "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PASSWORD_SECRET_ARN",
        "BASELINES_FILE",
    ]:
        val = os.getenv(key)
        if val:
            props[key] = val

    return props


def _resolve_secret(arn: str, region: str) -> str:
    import boto3
    sm = boto3.client("secretsmanager", region_name=region)
    return sm.get_secret_value(SecretId=arn)["SecretString"]


def _load_baselines(baselines_path: str) -> dict:
    if baselines_path.startswith("s3://"):
        import boto3, tempfile
        parts = baselines_path[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        tmp = tempfile.mktemp(suffix=".json")
        s3.download_file(bucket, key, tmp)
        with open(tmp) as f:
            return json.load(f)
    p = Path(baselines_path)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _ensure_schema(host: str, port: int, db: str, user: str, password: str):
    """Create tables on first run (plain PostgreSQL on RDS)."""
    import psycopg2
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sensor_aggregates (
                window_start  TIMESTAMPTZ     NOT NULL,
                window_end    TIMESTAMPTZ     NOT NULL,
                sensor_id     TEXT            NOT NULL,
                city          TEXT            NOT NULL,
                station_name  TEXT            NOT NULL,
                latitude      DOUBLE PRECISION,
                longitude     DOUBLE PRECISION,
                avg_pm2_5     DOUBLE PRECISION,
                max_pm2_5     DOUBLE PRECISION,
                avg_pm10      DOUBLE PRECISION,
                avg_no2       DOUBLE PRECISION,
                avg_o3        DOUBLE PRECISION,
                avg_so2       DOUBLE PRECISION,
                avg_aqi       DOUBLE PRECISION,
                reading_count BIGINT,
                created_at    TIMESTAMPTZ     DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sa_window_start
            ON sensor_aggregates (window_start DESC);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_alerts (
                id                  SERIAL PRIMARY KEY,
                alert_id            TEXT            NOT NULL,
                sensor_id           TEXT            NOT NULL,
                city                TEXT            NOT NULL,
                event_type          TEXT            NOT NULL,
                severity            TEXT,
                peak_pm2_5          DOUBLE PRECISION,
                avg_aqi             DOUBLE PRECISION,
                duration_minutes    INT             DEFAULT 0,
                consecutive_windows INT             DEFAULT 0,
                trend               TEXT,
                latitude            DOUBLE PRECISION,
                longitude           DOUBLE PRECISION,
                timestamp           TIMESTAMPTZ     DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_aq_alerts_ts
            ON air_quality_alerts (timestamp DESC);
        """)
        conn.commit()
    conn.close()
    logger.info("PostgreSQL schema ready")


# ─────────────────────────────────────────────────────────────────────────────
# Alert state machine
# ─────────────────────────────────────────────────────────────────────────────

class AirQualityAlertFunction(KeyedProcessFunction):
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
            "status": "normal", "onset_time": None,
            "windows_elevated": 0, "windows_pending": 0, "windows_recovery": 0,
        }
        history = list(self.history.get())
        history.append({"avg_pm2_5": row["avg_pm2_5"], "max_pm2_5": row["max_pm2_5"], "avg_aqi": row["avg_aqi"]})
        history = history[-HISTORY_SIZE:]
        self.history.update(history)

        is_elevated = self._is_elevated(row["sensor_id"], row["avg_pm2_5"], row["avg_aqi"])
        trend       = self._trend(history)
        peak_pm2_5  = max(w["max_pm2_5"] for w in history)

        if state["status"] == "normal":
            if is_elevated:
                state["windows_pending"] += 1
                if state["windows_pending"] >= ONSET_WINDOWS:
                    state.update({"status": "firing", "onset_time": datetime.now(timezone.utc).isoformat(),
                                  "windows_elevated": state["windows_pending"], "windows_pending": 0, "windows_recovery": 0})
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
                    duration = int((datetime.now(timezone.utc) -
                                    datetime.fromisoformat(state["onset_time"])).total_seconds() / 60)
                    yield self._make_alert(row, "recovery", state, trend, peak_pm2_5, duration)
                    state = {"status": "normal", "onset_time": None,
                             "windows_elevated": 0, "windows_pending": 0, "windows_recovery": 0}
        self.alert_state.update(state)


# ─────────────────────────────────────────────────────────────────────────────
# TimescaleDB / psycopg2 sinks
# ─────────────────────────────────────────────────────────────────────────────

class PostgresAggregatesSink(MapFunction):
    """MapFunction-based sink: PyFlink local mode requires MapFunction for pure-Python sinks."""
    def __init__(self, host: str, port: int, db: str, user: str, password: str):
        self._host     = host
        self._port     = port
        self._db       = db
        self._user     = user
        self._password = password
        self._conn     = None

    def __reduce__(self):
        return (self.__class__, (self._host, self._port, self._db, self._user, self._password))

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            import psycopg2
            self._conn = psycopg2.connect(
                host=self._host, port=self._port,
                dbname=self._db, user=self._user, password=self._password,
            )
        return self._conn

    @staticmethod
    def _to_dt(val):
        if isinstance(val, datetime):
            return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
        return datetime.now(timezone.utc)

    def map(self, row):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sensor_aggregates (
                        window_start, window_end, sensor_id, city, station_name,
                        latitude, longitude,
                        avg_pm2_5, max_pm2_5, avg_pm10, avg_no2, avg_o3, avg_so2,
                        avg_aqi, reading_count
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (
                    self._to_dt(row["window_start"]),
                    self._to_dt(row["window_end"]),
                    row["sensor_id"], row["city"], row["station_name"],
                    float(row["latitude"]),  float(row["longitude"]),
                    float(row["avg_pm2_5"]), float(row["max_pm2_5"]),
                    float(row["avg_pm10"]),  float(row["avg_no2"]),
                    float(row["avg_o3"]),    float(row["avg_so2"]),
                    float(row["avg_aqi"]),   int(row["reading_count"]),
                ))
            conn.commit()
        except Exception as e:
            logger.error(f"Postgres aggregates write error: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            self._conn = None
        return True


class PostgresAlertsSink(MapFunction):
    """MapFunction-based sink: PyFlink local mode requires MapFunction for pure-Python sinks."""
    def __init__(self, host: str, port: int, db: str, user: str, password: str):
        self._host     = host
        self._port     = port
        self._db       = db
        self._user     = user
        self._password = password
        self._conn     = None

    def __reduce__(self):
        return (self.__class__, (self._host, self._port, self._db, self._user, self._password))

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            import psycopg2
            self._conn = psycopg2.connect(
                host=self._host, port=self._port,
                dbname=self._db, user=self._user, password=self._password,
            )
        return self._conn

    def map(self, json_str: str):
        try:
            a = json.loads(json_str)
        except Exception:
            return True
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO air_quality_alerts (
                        alert_id, sensor_id, city, event_type, severity,
                        peak_pm2_5, avg_aqi, duration_minutes, consecutive_windows,
                        trend, latitude, longitude, timestamp
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    a.get("alert_id", str(uuid.uuid4())),
                    a.get("sensor_id", ""),
                    a.get("city", ""),
                    a.get("event_type", ""),
                    a.get("severity", "unknown"),
                    float(a.get("peak_pm2_5",       0.0)),
                    float(a.get("avg_aqi",           0.0)),
                    int(a.get("duration_minutes",    0)),
                    int(a.get("consecutive_windows", 0)),
                    a.get("trend", "stable"),
                    float(a.get("latitude",  0.0)),
                    float(a.get("longitude", 0.0)),
                    a.get("timestamp", datetime.now(timezone.utc).isoformat()),
                ))
            conn.commit()
        except Exception as e:
            logger.error(f"Postgres alerts write error: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            self._conn = None
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Kafka source and sinks
# ─────────────────────────────────────────────────────────────────────────────

def _create_source(t_env, kafka_bootstrap: str, source_topic: str):
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
            'topic'                         = '{source_topic}',
            'properties.bootstrap.servers'  = '{kafka_bootstrap}',
            'properties.group.id'           = 'flink-processor',
            'scan.startup.mode'             = 'latest-offset',
            'format'                        = 'json',
            'json.fail-on-missing-field'    = 'false',
            'json.ignore-parse-errors'      = 'true'
        )
    """)


def _create_aggregated_kafka_sink(t_env, kafka_bootstrap: str, agg_topic: str):
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
            'topic'                        = '{agg_topic}',
            'properties.bootstrap.servers' = '{kafka_bootstrap}',
            'format'                       = 'json',
            'json.timestamp-format.standard' = 'ISO-8601'
        )
    """)


def _create_alerts_kafka_sink(t_env, kafka_bootstrap: str, alerts_topic: str):
    t_env.execute_sql(f"""
        CREATE TABLE alerts_sink (
            message STRING
        ) WITH (
            'connector'                    = 'kafka',
            'topic'                        = '{alerts_topic}',
            'properties.bootstrap.servers' = '{kafka_bootstrap}',
            'format'                       = 'raw'
        )
    """)


def _window_aggregation(t_env):
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
    logger.info("Starting Air Quality Flink Stream Processor (AWS / TimescaleDB edition)")

    props = _load_app_properties()
    kafka_bootstrap  = props.get("KAFKA_BOOTSTRAP",                "broker:29092")
    aws_region       = props.get("AWS_REGION",                     "eu-central-1")
    postgres_host    = props.get("POSTGRES_HOST",                  "localhost")
    postgres_port    = int(props.get("POSTGRES_PORT",              "5432"))
    postgres_db      = props.get("POSTGRES_DB",                    "airquality")
    postgres_user    = props.get("POSTGRES_USER",                  "airquality")
    postgres_password = props.get("POSTGRES_PASSWORD",             "")
    password_secret  = props.get("POSTGRES_PASSWORD_SECRET_ARN",   "")
    baselines_path   = props.get("BASELINES_FILE",
                                  str(Path(__file__).parent / "baselines" / "baselines.json"))

    if password_secret and not postgres_password:
        logger.info("Resolving DB password from Secrets Manager")
        postgres_password = _resolve_secret(password_secret, aws_region)

    logger.info(f"Kafka: {kafka_bootstrap} | Postgres: {postgres_host}:{postgres_port}/{postgres_db}")

    try:
        _ensure_schema(postgres_host, postgres_port, postgres_db, postgres_user, postgres_password)
    except Exception as e:
        logger.warning(f"Schema init failed (continuing): {e}")

    env   = StreamExecutionEnvironment.get_execution_environment()
    t_env = StreamTableEnvironment.create(env)

    env.set_parallelism(1)
    t_env.get_config().set("execution.checkpointing.interval", "60s")
    t_env.get_config().set("execution.checkpointing.mode", "EXACTLY_ONCE")
    t_env.get_config().set("table.exec.source.idle-timeout", "5000")

    baselines: dict = {}
    try:
        baselines = _load_baselines(baselines_path)
        logger.info(f"Loaded baselines for {len(baselines)} sensors from {baselines_path}")
    except Exception as e:
        logger.warning(f"Could not load baselines from {baselines_path}: {e} — using fixed thresholds")

    _create_source(t_env, kafka_bootstrap, "air-quality-raw")

    aggregated_table  = _window_aggregation(t_env)
    aggregated_stream = t_env.to_data_stream(aggregated_table)

    alert_json_stream = (
        aggregated_stream
        .key_by(lambda row: row["sensor_id"])
        .process(AirQualityAlertFunction(baselines), output_type=Types.STRING())
    )

    # PostgreSQL sinks. Use .print() as a terminal sink so Flink includes these
    # branches in the job graph and env.execute() actually runs them.
    aggregated_stream.map(
        PostgresAggregatesSink(postgres_host, postgres_port, postgres_db, postgres_user, postgres_password),
        output_type=Types.BOOLEAN()
    ).print("pg-agg")

    alert_json_stream.map(
        PostgresAlertsSink(postgres_host, postgres_port, postgres_db, postgres_user, postgres_password),
        output_type=Types.BOOLEAN()
    ).print("pg-alert")

    # env.execute() is blocking for streaming jobs — keeps the JVM alive.
    logger.info("Flink job submitted")
    env.execute("air-quality-job")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        sys.exit(1)