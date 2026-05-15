import os

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "air-quality-alerts"
KAFKA_GROUP = "alerting-email-consumer"

SMTP_HOST = os.getenv("SMTP_HOST", "mailhog")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() == "true"
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@airquality.local")
ALERT_TO = os.getenv("ALERT_EMAIL_TO", "admin@airquality.local")

SMTP_TIMEOUT_SECONDS = 10
CONSUMER_POLL_TIMEOUT_SECONDS = 1.0

PM25_SAFE_THRESHOLD = 25
AQI_MAX_SCALE = 5

SEVERITY_LABEL = {
    "good": "Good",
    "fair": "Fair",
    "moderate": "Moderate",
    "poor": "Poor",
    "very_poor": "Very Poor",
}
