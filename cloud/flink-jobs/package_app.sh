#!/usr/bin/env bash
# Packages the PyFlink application as a ZIP for Amazon Managed Service for Apache Flink.
# Run from the cloud/flink-jobs/ directory.
# Usage: ./package_app.sh [output_zip] [s3_path]
#   output_zip  path for the produced archive (default: application.zip)
#   s3_path     if provided, uploads to S3 after packaging, e.g. s3://my-bucket/flink-app/application.zip

set -euo pipefail

OUTPUT="${1:-application.zip}"
S3_PATH="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# Amazon Managed Flink requires at least one JAR in the ZIP.
# The Kafka SQL connector is needed at runtime; flink-python enables PyFlink execution.
KAFKA_JAR="flink-sql-connector-kafka-3.0.2-1.18.jar"
KAFKA_JAR_URL="https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.0.2-1.18/${KAFKA_JAR}"

mkdir -p "$BUILD_DIR/lib"

# Cache JARs next to the script to avoid re-downloading on every build
JAR_CACHE="$SCRIPT_DIR/lib"
mkdir -p "$JAR_CACHE"

if [ ! -f "$JAR_CACHE/$KAFKA_JAR" ]; then
    echo "==> Downloading Kafka connector JAR..."
    curl -fsSL -o "$JAR_CACHE/$KAFKA_JAR" "$KAFKA_JAR_URL"
fi
cp "$JAR_CACHE/$KAFKA_JAR" "$BUILD_DIR/lib/"

echo "==> Installing Python dependencies into $BUILD_DIR..."
# apache-flink is provided by the Managed Flink runtime — exclude it.
# Force linux x86_64 manylinux wheels so binaries run on Managed Flink (Amazon Linux, x86_64).
# boto3/botocore are pure-Python so --only-binary doesn't affect them.
grep -v "apache-flink" "$SCRIPT_DIR/requirements.txt" | \
  pip install --quiet --target "$BUILD_DIR" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 310 \
    --only-binary=:all: \
    -r /dev/stdin

echo "==> Copying application source..."
cp "$SCRIPT_DIR/src/stream_processor.py" "$BUILD_DIR/"
mkdir -p "$BUILD_DIR/baselines"
if [ -f "$SCRIPT_DIR/src/baselines/baselines.json" ]; then
    cp "$SCRIPT_DIR/src/baselines/baselines.json" "$BUILD_DIR/baselines/"
else
    echo "{}" > "$BUILD_DIR/baselines/baselines.json"
    echo "    WARNING: baselines.json not found — using empty fallback"
fi

echo "==> Creating $OUTPUT..."
(cd "$BUILD_DIR" && zip -qr "$SCRIPT_DIR/$OUTPUT" .)

echo "==> Done: $OUTPUT ($(du -sh "$SCRIPT_DIR/$OUTPUT" | cut -f1))"

if [ -n "$S3_PATH" ]; then
    echo "==> Uploading to $S3_PATH..."
    aws s3 cp "$SCRIPT_DIR/$OUTPUT" "$S3_PATH"
    echo "==> Upload complete."
fi