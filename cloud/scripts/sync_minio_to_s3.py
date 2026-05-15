import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

from config import (
    AWS_REGION,
    DST_BUCKET,
    MINIO_ACCESS,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET,
    PROGRESS_LOG_EVERY,
    SRC_BUCKET,
    WORKERS,
)


def make_minio():
    """Build a boto3 S3 client pointed at the configured MinIO endpoint.

    Returns:
        A configured boto3 S3 client instance.
    """
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name=MINIO_REGION,
    )


def make_aws():
    """Build a boto3 S3 client for the configured AWS region.

    Returns:
        A configured boto3 S3 client instance.
    """
    return boto3.client("s3", region_name=AWS_REGION)


def list_keys(s3, bucket: str) -> list[str]:
    """List all object keys in a bucket.

    Args:
        s3: A boto3 S3 client.
        bucket: Name of the bucket to enumerate.

    Returns:
        A list with every object key in the bucket.
    """
    paginator = s3.get_paginator("list_objects_v2")
    return [
        obj["Key"]
        for page in paginator.paginate(Bucket=bucket)
        for obj in page.get("Contents", [])
    ]


def copy_key(key: str) -> tuple[str, bool]:
    """Copy a single object from MinIO to AWS S3.

    Args:
        key: Object key shared between source and destination buckets.

    Returns:
        A two-tuple ``(key, True)`` once the copy completes.
    """
    src = make_minio()
    dst = make_aws()
    body = src.get_object(Bucket=SRC_BUCKET, Key=key)["Body"].read()
    dst.put_object(Bucket=DST_BUCKET, Key=key, Body=body)
    return (key, True)


def main() -> None:
    """Sync every object from the MinIO source bucket to the AWS destination.

    Returns:
        None.
    """
    src = make_minio()
    dst = make_aws()

    print(f"Source : minio://{SRC_BUCKET}  ({MINIO_ENDPOINT})")
    print(f"Dest   : s3://{DST_BUCKET}  ({AWS_REGION})\n")

    keys = list_keys(src, SRC_BUCKET)
    if not keys:
        print(f"MinIO bucket '{SRC_BUCKET}' is empty — nothing to sync.")
        sys.exit(1)

    print(f"Found {len(keys):,} objects to copy\n")

    existing = set(list_keys(dst, DST_BUCKET))
    to_copy = [k for k in keys if k not in existing]
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
            if i % PROGRESS_LOG_EVERY == 0 or i == len(to_copy):
                print(
                    f"  [{i:>6}/{len(to_copy)}  {i / len(to_copy) * 100:5.1f}%]  "
                    f"done={done}"
                )

    print(f"\nSync complete. {done}/{len(to_copy)} objects copied to s3://{DST_BUCKET}")


if __name__ == "__main__":
    main()
