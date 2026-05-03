CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS sensor_aggregates (
    window_start  TIMESTAMPTZ NOT NULL,
    window_end    TIMESTAMPTZ NOT NULL,
    sensor_id     TEXT        NOT NULL,
    city          TEXT        NOT NULL,
    station_name  TEXT        NOT NULL,
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
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('sensor_aggregates', 'window_start', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_agg_sensor_time ON sensor_aggregates (sensor_id, window_start DESC);
CREATE INDEX IF NOT EXISTS idx_agg_city        ON sensor_aggregates (city, window_start DESC);

CREATE TABLE IF NOT EXISTS air_quality_alerts (
    alert_id             TEXT        NOT NULL,
    sensor_id            TEXT        NOT NULL,
    city                 TEXT        NOT NULL,
    latitude             DOUBLE PRECISION,
    longitude            DOUBLE PRECISION,
    event_type           TEXT        NOT NULL,
    duration_minutes     INT         NOT NULL DEFAULT 0,
    consecutive_windows  INT         NOT NULL DEFAULT 0,
    peak_pm2_5           DOUBLE PRECISION,
    avg_aqi              DOUBLE PRECISION,
    trend                TEXT,
    severity             TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('air_quality_alerts', 'created_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_alert_sensor_time ON air_quality_alerts (sensor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_city        ON air_quality_alerts (city, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_event_type  ON air_quality_alerts (event_type, created_at DESC);