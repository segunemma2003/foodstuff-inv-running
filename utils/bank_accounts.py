"""Resolve bank accounts for invoice/quotation PDFs.

Prefer the customer's generated FS Credit / wallet account (from Foodstuff Store).
Fall back to NI admin-configured PaymentAccount rows only when the customer has none.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import httpx

import models

FOODSTUFF_API_URL = os.getenv("FOODSTUFF_API_URL", "").rstrip("/")
FOODSTUFF_API_KEY = os.getenv("FOODSTUFF_API_KEY", "")
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _company_accounts(db) -> list:
    return (
        db.query(models.PaymentAccount)
        .filter(models.PaymentAccount.is_active == True)  # noqa: E712
        .order_by(models.PaymentAccount.is_default.desc())
        .all()
    )


def _fetch_customer_dva(inventory_customer_id: int) -> list[SimpleNamespace]:
    if not FOODSTUFF_API_URL or not FOODSTUFF_API_KEY or not inventory_customer_id:
        return []
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{FOODSTUFF_API_URL}/api/internal/ni/payment-accounts",
                params={"inventoryCustomerId": inventory_customer_id},
                headers={
                    "Authorization": f"Bearer {FOODSTUFF_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            return []
        rows = resp.json() or []
        out: list[SimpleNamespace] = []
        for a in rows:
            number = a.get("accountNumber") or a.get("account_number")
            if not number:
                continue
            out.append(
                SimpleNamespace(
                    bank_name=a.get("bankName") or a.get("bank_name") or "",
                    account_number=number,
                    account_name=a.get("accountName") or a.get("account_name") or "Foodstuff Store",
                )
            )
        return out
    except Exception:
        return []


def resolve_bank_accounts_for_customer(db, customer_id: int | None) -> list[Any]:
    """Customer generated account first; else NI admin company accounts."""
    if customer_id:
        dva = _fetch_customer_dva(int(customer_id))
        if dva:
            return dva
    return _company_accounts(db)
