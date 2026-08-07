import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from dependencies import get_current_user, require_roles
import models

FOODSTUFF_API_URL = os.getenv("FOODSTUFF_API_URL", "")
FOODSTUFF_API_KEY = os.getenv("FOODSTUFF_API_KEY", "")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

router = APIRouter(prefix="/custom-orders", tags=["Custom Orders"])

_require_manager = require_roles("admin", "manager")


@router.get("")
async def list_custom_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = None,
    _: models.User = Depends(_require_manager),
):
    """Proxy GET /api/admin/procurement from foodstuff-api."""
    if not FOODSTUFF_API_URL or not FOODSTUFF_API_KEY:
        return {"items": [], "total": 0}

    params: dict = {"skip": skip, "limit": limit}
    if status:
        params["status"] = status

    headers = {
        "Authorization": f"Bearer {FOODSTUFF_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{FOODSTUFF_API_URL}/api/admin/procurement",
                params=params,
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {"items": data, "total": len(data)}
            return data
        # Service key is not an FSS admin JWT — don't bubble 401 or the NI
        # frontend clears the staff session and boots the user to /login.
        if resp.status_code in (401, 403):
            return {"items": [], "total": 0}
        raise HTTPException(status_code=502, detail="Failed to fetch custom orders")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Foodstuff API unavailable")
