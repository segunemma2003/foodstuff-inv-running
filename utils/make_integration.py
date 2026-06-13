import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from utils.s3 import presigned_url

SUPPORT_EMAIL = "support@foodstuff.store"


def _clean_document_number(doc_number: str) -> str:
    """Remove all punctuation and non-alphanumeric characters from a document number."""
    return re.sub(r"[^A-Za-z0-9]", "", doc_number)


def send_document_to_make_from_s3(
    doc_type: str,
    document_number: str,
    s3_key: str,
    filename: str,
    customer_name: str = "",
    extra: Optional[dict] = None,
) -> bool:
    """
    Sends document metadata and a presigned S3 URL to Make.
    Returns False when webhook is not configured.
    Also sends a notification copy to support@foodstuff.store.
    """
    webhook_url = os.getenv("MAKE_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    clean_number = _clean_document_number(document_number)

    payload = {
        "doc_type": doc_type,
        "document_number": clean_number,
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
    if extra:
        payload.update(extra)
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
        pass

    # Send notification copy to support
    try:
        from utils.email import send_email
        doc_label = doc_type.replace("_", " ").title()
        subject = f"{doc_label} sent to Make: {clean_number}"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px">
          <h2 style="color:#1a5276">{doc_label} Sent to Make</h2>
          <table style="border-collapse:collapse;width:100%;margin:16px 0">
            <tr style="background:#f2f4f6">
              <td style="padding:8px;font-weight:bold">Document Number</td>
              <td style="padding:8px">{clean_number}</td>
            </tr>
            <tr>
              <td style="padding:8px;font-weight:bold">Customer</td>
              <td style="padding:8px">{customer_name}</td>
            </tr>
            <tr style="background:#f2f4f6">
              <td style="padding:8px;font-weight:bold">File</td>
              <td style="padding:8px">{filename}</td>
            </tr>
            <tr>
              <td style="padding:8px;font-weight:bold">Sent At</td>
              <td style="padding:8px">{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</td>
            </tr>
          </table>
        </div>"""
        text = (
            f"{doc_label} sent to Make.\n"
            f"Document: {clean_number}\n"
            f"Customer: {customer_name}\n"
            f"File: {filename}"
        )
        send_email(to=SUPPORT_EMAIL, subject=subject, html=html, text=text)
    except Exception:
        pass  # notification failure must never block the Make webhook

    return True
