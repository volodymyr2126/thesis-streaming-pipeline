import json
import logging
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from confluent_kafka import Consumer, KafkaError

from config import (
    ALERT_TO,
    AQI_MAX_SCALE,
    CONSUMER_POLL_TIMEOUT_SECONDS,
    KAFKA_BOOTSTRAP,
    KAFKA_GROUP,
    KAFKA_TOPIC,
    PM25_SAFE_THRESHOLD,
    SEVERITY_LABEL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USE_TLS,
    SMTP_USER,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _send(subject: str, body: str) -> None:
    """Send a plain-text email through the configured SMTP server.

    Args:
        subject: Subject line for the outgoing email.
        body: Plain-text body of the email.

    Returns:
        None.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ALERT_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if SMTP_USE_TLS:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [ALERT_TO], msg.as_string())

    logger.info(f"Email sent: {subject}")


def _onset_email(alert: dict) -> tuple[str, str]:
    """Build subject and body for an air-quality degradation onset alert.

    Args:
        alert: Decoded JSON payload from the alerts Kafka topic.

    Returns:
        A two-tuple ``(subject, body)`` ready to pass to :func:`_send`.
    """
    city = alert["city"]
    severity = SEVERITY_LABEL.get(
        alert.get("severity", ""), alert.get("severity", "Unknown")
    )
    peak_pm25 = alert.get("peak_pm2_5", 0.0)
    avg_aqi = alert.get("avg_aqi", 0)
    trend = alert.get("trend", "stable").upper()
    windows = alert.get("consecutive_windows", 1)

    subject = f"[AIR QUALITY ALERT] {city} — {severity} (PM2.5: {peak_pm25:.1f} µg/m³)"
    body = f"""\
Air Quality Degradation Detected
=================================
City:        {city}
Sensor:      {alert.get("sensor_id")}
Coordinates: {alert.get("latitude")}, {alert.get("longitude")}

Severity:  {severity}
Trend:     {trend}

Measurements
------------
Peak PM2.5:  {peak_pm25:.1f} µg/m³   (safe threshold: {PM25_SAFE_THRESHOLD} µg/m³)
Average AQI: {avg_aqi:.0f} / {AQI_MAX_SCALE}        (European Air Quality Index)

Consecutive elevated windows: {windows} (~{windows} minute(s) sustained)

---
Air Quality Monitoring Pipeline | automated alert
"""
    return subject, body


def _recovery_email(alert: dict) -> tuple[str, str]:
    """Build subject and body for an air-quality recovery alert.

    Args:
        alert: Decoded JSON payload from the alerts Kafka topic.

    Returns:
        A two-tuple ``(subject, body)`` ready to pass to :func:`_send`.
    """
    city = alert["city"]
    duration = alert.get("duration_minutes", alert.get("consecutive_windows", 0))
    peak = alert.get("peak_pm2_5", 0.0)

    subject = f"[AIR QUALITY RECOVERY] {city} — Levels returning to normal"
    body = f"""\
Air Quality Recovery
====================
City:   {city}
Sensor: {alert.get("sensor_id")}

Air quality has returned to normal levels.
Duration of elevated conditions: ~{duration} minute(s)
Peak PM2.5 during event:         {peak:.1f} µg/m³

---
Air Quality Monitoring Pipeline | automated alert
"""
    return subject, body


def main() -> None:
    """Run the Kafka consumer loop, dispatching each alert to SMTP.

    Returns:
        None.
    """
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": KAFKA_GROUP,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([KAFKA_TOPIC])
    logger.info(
        f"Listening on {KAFKA_TOPIC}, sending to {ALERT_TO} via {SMTP_HOST}:{SMTP_PORT}"
    )

    try:
        while True:
            msg = consumer.poll(timeout=CONSUMER_POLL_TIMEOUT_SECONDS)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error(f"Kafka error: {msg.error()}")
                continue

            try:
                alert = json.loads(msg.value().decode())
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
