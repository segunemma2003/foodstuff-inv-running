import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from utils.s3 import presigned_url


def send_document_to_make_from_s3(
    doc_type: str,
    document_number: str,
    s3_key: str,
    filename: str,
    customer_name: str = "",
) -> bool:
    """
    Sends document metadata and a presigned S3 URL to Make.
    Returns False when webhook is not configured.
    """
    webhook_url = os.getenv("MAKE_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    payload = {
        "doc_type": doc_type,
        "document_number": document_number,
        "customer_name": customer_name,
        "filename": filename,
        "s3_key": s3_key,
        "file_url": presigned_url(
            key=s3_key,
            filename=filename,
            content_type="application/pdf",
            expiry=86400,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    token: Optional[str] = os.getenv("MAKE_WEBHOOK_TOKEN")

    request = urllib.request.Request(
        webhook_url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20):
        return True
