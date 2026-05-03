"""
cloud/scripts/sync_minio_to_s3.py

If you already have data in local MinIO, this script copies it to AWS S3
instead of re-fetching everything from OWM.

Copies both:
  minio://air-quality-historical/  →  s3://<BUCKET>/  (hourly Parquet)
  minio://air-quality-minutely/    →  s3://<BUCKET>/  (minute Parquet, if it exists)

After syncing, run cloud/scripts/expand_to_minutely.py if the minutely
bucket was empty and you only synced the historical data.

Usage:
    export BUCKET=$(terraform -chdir=cloud/infrastructure/environments/dev output -raw data_lake_bucket_name)
    python cloud/scripts/sync_minio_to_s3.py

Optional env vars:
    MINIO_ENDPOINT   (default http://localhost:9000)
    MINIO_ACCESS_KEY (default minioadmin)
    MINIO_SECRET_KEY (default minioadmin)
    SRC_BUCKET       MinIO bucket to copy from (default air-quality-minutely)
    BUCKET           AWS S3 destination bucket (required)
    AWS_DEFAULT_REGION (default eu-central-1)
    WORKERS          (default 16)
"""

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT",  "http://localhost:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin")
SRC_BUCKET     = os.getenv("SRC_BUCKET",       "air-quality-minutely")
DST_BUCKET     = os.environ["BUCKET"]
AWS_REGION     = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
WORKERS        = int(os.getenv("WORKERS", "16"))


def make_minio():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name="us-east-1",
    )


def make_aws():
    return boto3.client("s3", region_name=AWS_REGION)


def list_keys(s3, bucket: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    return [
        obj["Key"]
        for page in paginator.paginate(Bucket=bucket)
        for obj in page.get("Contents", [])
    ]


def copy_key(key: str) -> tuple[str, bool]:
    src = make_minio()
    dst = make_aws()
    body = src.get_object(Bucket=SRC_BUCKET, Key=key)["Body"].read()
    dst.put_object(Bucket=DST_BUCKET, Key=key, Body=body)
    return (key, True)


def main():
    src = make_minio()
    dst = make_aws()

    print(f"Source : minio://{SRC_BUCKET}  ({MINIO_ENDPOINT})")
    print(f"Dest   : s3://{DST_BUCKET}  ({AWS_REGION})\n")

    keys = list_keys(src, SRC_BUCKET)
    if not keys:
        print(f"MinIO bucket '{SRC_BUCKET}' is empty — nothing to sync.")
        sys.exit(1)

    print(f"Found {len(keys):,} objects to copy\n")

    # Check which keys already exist in S3
    existing = set(list_keys(dst, DST_BUCKET))
    to_copy  = [k for k in keys if k not in existing]
    print(f"Skipping {len(keys) - len(to_copy)} already-synced objects")
    print(f"Copying  {len(to_copy)} objects\n")

    if not to_copy:
        print("All objects already synced.")
        return

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(copy_key, k): k for k in to_copy}
        for i, fut in enumerate(as_completed(futures), start=1):
            key, ok = fut.result()
            if ok:
                done += 1
            if i % 200 == 0 or i == len(to_copy):
                print(f"  [{i:>6}/{len(to_copy)}  {i/len(to_copy)*100:5.1f}%]  done={done}")

    print(f"\nSync complete. {done}/{len(to_copy)} objects copied to s3://{DST_BUCKET}")


if __name__ == "__main__":
    main()