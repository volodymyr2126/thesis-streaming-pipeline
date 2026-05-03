"""Consumes air-quality-alerts from Kafka and sends email notifications via SMTP."""
import json
import logging
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from confluent_kafka import Consumer, KafkaError

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC     = "air-quality-alerts"
KAFKA_GROUP     = "alerting-email-consumer"

SMTP_HOST    = os.getenv("SMTP_HOST",     "mailhog")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS",  "false").lower() == "true"
SMTP_USER    = os.getenv("SMTP_USER",     "")
SMTP_PASS    = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM    = os.getenv("SMTP_FROM",     "alerts@airquality.local")
ALERT_TO     = os.getenv("ALERT_EMAIL_TO","admin@airquality.local")

_SEVERITY_LABEL = {
    "good":      "Good",
    "fair":      "Fair",
    "moderate":  "Moderate ⚠",
    "poor":      "Poor 🔴",
    "very_poor": "Very Poor 🟣",
}


def _send(subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = ALERT_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        if SMTP_USE_TLS:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [ALERT_TO], msg.as_string())

    logger.info(f"Email sent: {subject}")


def _onset_email(alert: dict) -> tuple[str, str]:
    city      = alert["city"]
    severity  = _SEVERITY_LABEL.get(alert.get("severity", ""), alert.get("severity", "Unknown"))
    peak_pm25 = alert.get("peak_pm2_5", 0.0)
    avg_aqi   = alert.get("avg_aqi", 0)
    trend     = alert.get("trend", "stable").upper()
    windows   = alert.get("consecutive_windows", 1)

    subject = f"[AIR QUALITY ALERT] {city} — {severity} (PM2.5: {peak_pm25:.1f} µg/m³)"
    body = f"""\
Air Quality Degradation Detected
=================================
City:        {city}
Sensor:      {alert.get('sensor_id')}
Coordinates: {alert.get('latitude')}, {alert.get('longitude')}

Severity:  {severity}
Trend:     {trend}

Measurements
------------
Peak PM2.5:  {peak_pm25:.1f} µg/m³   (safe threshold: 25 µg/m³)
Average AQI: {avg_aqi:.0f} / 5        (European Air Quality Index)

Consecutive elevated windows: {windows} (~{windows} minute(s) sustained)

---
Air Quality Monitoring Pipeline | automated alert
"""
    return subject, body


def _recovery_email(alert: dict) -> tuple[str, str]:
    city     = alert["city"]
    duration = alert.get("duration_minutes", alert.get("consecutive_windows", 0))
    peak     = alert.get("peak_pm2_5", 0.0)

    subject = f"[AIR QUALITY RECOVERY] {city} — Levels returning to normal"
    body = f"""\
Air Quality Recovery
====================
City:   {city}
Sensor: {alert.get('sensor_id')}

Air quality has returned to normal levels.
Duration of elevated conditions: ~{duration} minute(s)
Peak PM2.5 during event:         {peak:.1f} µg/m³

---
Air Quality Monitoring Pipeline | automated alert
"""
    return subject, body


def main() -> None:
    consumer = Consumer({
        "bootstrap.servers":  KAFKA_BOOTSTRAP,
        "group.id":           KAFKA_GROUP,
        "auto.offset.reset":  "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([KAFKA_TOPIC])
    logger.info(f"Listening on {KAFKA_TOPIC}, sending to {ALERT_TO} via {SMTP_HOST}:{SMTP_PORT}")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error(f"Kafka error: {msg.error()}")
                continue

            try:
                alert      = json.loads(msg.value().decode())
                event_type = alert.get("event_type", "")

                if event_type == "onset":
                    subject, body = _onset_email(alert)
                elif event_type == "recovery":
                    subject, body = _recovery_email(alert)
                else:
                    logger.warning(f"Unknown event_type: {event_type!r}")
                    continue

                try:
                    _send(subject, body)
                except Exception as e:
                    logger.error(f"SMTP send failed: {e}")

            except Exception as e:
                logger.error(f"Failed to process message: {e}", exc_info=True)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
