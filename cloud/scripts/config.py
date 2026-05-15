import os

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_REGION = "us-east-1"

SRC_BUCKET = os.getenv("SRC_BUCKET", "air-quality-minutely")
DST_BUCKET = os.environ.get("BUCKET", "")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
WORKERS = int(os.getenv("WORKERS", "16"))

PROGRESS_LOG_EVERY = 200
