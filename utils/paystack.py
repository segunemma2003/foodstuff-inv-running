"""
Paystack payment gateway integration.

Environment variables required:
  PAYSTACK_SECRET_KEY  — your Paystack secret key (sk_live_... or sk_test_...)
  PAYSTACK_PUBLIC_KEY  — your Paystack public key  (pk_live_... or pk_test_...)

All API calls are synchronous (used inside sync FastAPI route handlers).
"""
import os
import hmac
import hashlib
from decimal import Decimal

import httpx

PAYSTACK_SECRET_KEY: str = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY: str = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"


def is_configured() -> bool:
    """Return True if Paystack credentials are present in environment."""
    return bool(PAYSTACK_SECRET_KEY)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


# ─── Transaction helpers ──────────────────────────────────────────────────────

def initialize_transaction(
    email: str,
    amount_naira: Decimal,
    reference: str,
    invoice_number: str,
    customer_name: str,
) -> dict:
    """
    Create a Paystack transaction and return its authorization_url.

    Args:
        email:          Customer email address (required by Paystack).
        amount_naira:   Amount in Nigerian Naira; converted to kobo internally.
        reference:      Unique reference string (e.g. "PAY-INV-001-A3F7").
        invoice_number: Stored in transaction metadata.
        customer_name:  Stored in transaction metadata.

    Returns:
        Paystack API data dict with keys:
            authorization_url, access_code, reference

    Raises:
        httpx.HTTPStatusError: on non-2xx Paystack response.
        RuntimeError:          if PAYSTACK_SECRET_KEY is not set.
    """
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError(
            "PAYSTACK_SECRET_KEY is not configured. "
            "Set it in your environment or .env file."
        )

    amount_kobo = int(Decimal(str(amount_naira)) * 100)

    payload = {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "currency": "NGN",
        "metadata": {
            "invoice_number": invoice_number,
            "customer_name": customer_name,
        },
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=_headers(),
        )
        resp.raise_for_status()
        body = resp.json()

    if not body.get("status"):
        raise RuntimeError(f"Paystack error: {body.get('message', 'unknown')}")

    return body["data"]


def verify_transaction(reference: str) -> dict:
    """
    Verify a Paystack transaction by its reference.

    Returns:
        Paystack data dict. Key fields: status, amount, customer, paid_at.

    Raises:
        httpx.HTTPStatusError on non-2xx response.
    """
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not configured.")

    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_headers(),
        )
        resp.raise_for_status()
        body = resp.json()

    if not body.get("status"):
        raise RuntimeError(f"Paystack error: {body.get('message', 'unknown')}")

    return body["data"]


# ─── Webhook signature verification ──────────────────────────────────────────

def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify that an incoming webhook request genuinely came from Paystack.

    Paystack signs the raw request body with HMAC-SHA512 using your secret key
    and passes the hex digest in the 'x-paystack-signature' HTTP header.

    Returns False (never raises) so the caller can return 400 gracefully.
    """
    if not PAYSTACK_SECRET_KEY or not signature:
        return False
    computed = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        payload_bytes,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)
