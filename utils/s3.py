"""
Object storage helpers — Cloudflare R2 (or plain AWS S3).

Environment:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET
  AWS_S3_REGION   "auto" for R2 (default when AWS_ENDPOINT is set), e.g. "us-east-1" for AWS
  AWS_ENDPOINT    R2: https://<account_id>.r2.cloudflarestorage.com  (unset = AWS S3)
  AWS_PUBLIC_URL  public CDN base for public/ objects, e.g. https://cdn.foodstuff.store

Logical key layout (what callers pass and what the database stores):
  uploads/{uuid}.xlsx                — temporary bulk-upload input files
  jobs/{task_id}.pdf|.xlsx           — generated PDFs / reports
  invoices/{id}/signed_{uuid}.pdf    — signed invoices

On R2 the bucket is shared with other Foodstuff apps, so logical keys are
stored under PRIVATE_PREFIX (e.g. private/inventory/invoices/...). Keys that
already start with "public/" are left as-is (product images, served by the CDN).
On plain AWS nothing is prefixed, so existing keys keep working.
"""
import os
from functools import lru_cache

import boto3
from botocore.config import Config

PRIVATE_PREFIX = "private/inventory/"


def _bucket() -> str:
    return os.getenv("AWS_S3_BUCKET", "")


def _endpoint():
    return os.getenv("AWS_ENDPOINT") or None


@lru_cache(maxsize=4)
def _client_for(endpoint, region, key_id, secret):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _client():
    endpoint = _endpoint()
    region = os.getenv("AWS_S3_REGION") or ("auto" if endpoint else "us-east-1")
    if endpoint and region == "us-east-1":
        region = "auto"
    return _client_for(endpoint, region, os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY"))


def object_key(key: str) -> str:
    """Logical key -> key in the bucket."""
    if not _endpoint() or key.startswith(("public/", "private/")):
        return key
    return PRIVATE_PREFIX + key


def public_url(key: str) -> str:
    base = (os.getenv("AWS_PUBLIC_URL") or "").rstrip("/")
    if base:
        return f"{base}/{key}"
    if _endpoint():
        raise RuntimeError("AWS_PUBLIC_URL is not set; cannot build a public URL for R2 objects")
    region = os.getenv("AWS_S3_REGION") or "us-east-1"
    return f"https://{_bucket()}.s3.{region}.amazonaws.com/{key}"


def key_from_public_url(url: str):
    """Reverse of public_url(); None if the URL isn't one of ours."""
    base = (os.getenv("AWS_PUBLIC_URL") or "").rstrip("/")
    if base and url.startswith(base + "/"):
        return url[len(base) + 1:]
    return None


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes. Returns the (logical) key."""
    full = object_key(key)
    extra = {"CacheControl": "public, max-age=31536000, immutable"} if full.startswith("public/") else {}
    _client().put_object(Bucket=_bucket(), Key=full, Body=data, ContentType=content_type, **extra)
    return key


def download_bytes(key: str) -> bytes:
    resp = _client().get_object(Bucket=_bucket(), Key=object_key(key))
    return resp["Body"].read()


def delete_object(key: str) -> None:
    """Delete a single object (swallows errors so callers don't need try/except)."""
    try:
        if key.startswith("http"):
            key = key_from_public_url(key)
            if not key:
                return
        _client().delete_object(Bucket=_bucket(), Key=object_key(key))
    except Exception:
        pass


def presigned_url(key: str, filename: str, content_type: str, expiry: int = 3600) -> str:
    """
    Presigned GET URL valid for `expiry` seconds (default 1 hour).
    Sets Content-Disposition so the browser downloads with the human-friendly filename.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": _bucket(),
            "Key": object_key(key),
            "ResponseContentType": content_type,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=expiry,
    )
