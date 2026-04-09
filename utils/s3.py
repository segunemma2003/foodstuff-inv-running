"""
AWS S3 helper utilities.

All functions read credentials from environment variables:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET, AWS_S3_REGION

Key layout:
  uploads/{uuid}.xlsx   — temporary bulk-upload input files (deleted after processing)
  jobs/{task_id}.pdf    — generated PDFs  (kept until Celery result expires, ~2 h)
  jobs/{task_id}.xlsx   — generated Excel reports
"""
import os
import boto3

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
AWS_S3_REGION = os.getenv("AWS_S3_REGION", "us-east-1")


def _client():
    return boto3.client(
        "s3",
        region_name=AWS_S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to S3. Returns the key."""
    _client().put_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def download_bytes(key: str) -> bytes:
    """Download an S3 object and return its bytes."""
    resp = _client().get_object(Bucket=AWS_S3_BUCKET, Key=key)
    return resp["Body"].read()


def delete_object(key: str) -> None:
    """Delete a single S3 object (swallows errors so callers don't need try/except)."""
    try:
        _client().delete_object(Bucket=AWS_S3_BUCKET, Key=key)
    except Exception:
        pass


def presigned_url(key: str, filename: str, content_type: str, expiry: int = 3600) -> str:
    """
    Generate a presigned GET URL valid for `expiry` seconds (default 1 hour).
    Sets Content-Disposition so the browser downloads with the human-friendly filename.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": AWS_S3_BUCKET,
            "Key": key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=expiry,
    )
