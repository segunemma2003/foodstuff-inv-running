import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from dependencies import require_roles
import models

FOODSTUFF_API_URL = os.getenv("FOODSTUFF_API_URL", "").rstrip("/")
FOODSTUFF_API_KEY = os.getenv("FOODSTUFF_API_KEY", "")

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

router = APIRouter(prefix="/custom-orders", tags=["Custom Orders"])

# Sales owns customers — they must be able to review and accept custom orders
_require_custom_orders = require_roles("admin", "manager", "sales")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {FOODSTUFF_API_KEY}",
        "Content-Type": "application/json",
    }


def _configured() -> bool:
    return bool(FOODSTUFF_API_URL and FOODSTUFF_API_KEY)


class ApproveBody(BaseModel):
    notes: Optional[str] = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=1)


@router.get("")
async def list_custom_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = None,
    _: models.User = Depends(_require_custom_orders),
):
    """Proxy custom orders from Foodstuff Store (service-key internal API)."""
    if not _configured():
        return {"items": [], "total": 0}

    params: dict = {"skip": skip, "limit": limit}
    if status:
        params["status"] = status

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{FOODSTUFF_API_URL}/api/internal/ni/procurement",
                params=params,
                headers=_headers(),
            )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {"items": data, "total": len(data)}
            return data
        if resp.status_code in (401, 403):
            return {"items": [], "total": 0}
        raise HTTPException(status_code=502, detail="Failed to fetch custom orders")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Foodstuff API unavailable")


@router.post("/{req_id}/approve")
async def approve_custom_order(
    req_id: str,
    body: ApproveBody,
    _: models.User = Depends(_require_custom_orders),
):
    """Accept a customer custom order (moves to sourcing)."""
    if not _configured():
        raise HTTPException(503, "Foodstuff API not configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{FOODSTUFF_API_URL}/api/internal/ni/procurement/{req_id}/approve",
                json={"notes": body.notes},
                headers=_headers(),
            )
        if resp.status_code == 200:
            return resp.json()
        detail = "Failed to approve order"
        try:
            detail = resp.json().get("detail") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502 if resp.status_code >= 500 else resp.status_code, detail=detail)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Foodstuff API unavailable")


@router.post("/{req_id}/reject")
async def reject_custom_order(
    req_id: str,
    body: RejectBody,
    _: models.User = Depends(_require_custom_orders),
):
    """Reject a customer custom order."""
    if not _configured():
        raise HTTPException(503, "Foodstuff API not configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{FOODSTUFF_API_URL}/api/internal/ni/procurement/{req_id}/reject",
                json={"reason": body.reason},
                headers=_headers(),
            )
        if resp.status_code == 200:
            return resp.json()
        detail = "Failed to reject order"
        try:
            detail = resp.json().get("detail") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502 if resp.status_code >= 500 else resp.status_code, detail=detail)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Foodstuff API unavailable")
