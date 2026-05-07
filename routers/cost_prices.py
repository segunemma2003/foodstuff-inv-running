from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_manager_or_operations
import models
import schemas
from services import cost_price_service

router = APIRouter(prefix="/cost-prices", tags=["Cost Prices"])


@router.get("", response_model=List[schemas.CostPriceOut])
def list_cost_prices(
    product_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return cost_price_service.list_cost_prices(db, product_id=product_id, skip=skip, limit=limit)


@router.post("", response_model=schemas.CostPriceOut, status_code=201)
def add_cost_price(
    body: schemas.CostPriceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return cost_price_service.add_cost_price(db, body, current_user)


@router.put("/{cp_id}", response_model=schemas.CostPriceOut)
def update_cost_price(
    cp_id: int,
    body: schemas.CostPriceUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return cost_price_service.update_cost_price(db, cp_id, body, current_user)


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_cost_prices(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    """
    Upload an Excel file to S3 and queue parsing via Celery.
    Returns a task_id immediately (< 50 ms). Poll /api/v1/jobs/{task_id} for result.

    Required columns: product_name, uom, market_name, cost_price
    Effective date is applied immediately (today).

    Rows with any required field missing are skipped without error. Scanning stops after
    three consecutive completely blank rows. Existing products are never reassigned to
    a different market.
    """
    return await cost_price_service.bulk_upload_cost_prices(file, current_user)


@router.get("/template")
def download_template(_: models.User = Depends(get_current_user)):
    """Download Excel template for bulk cost price upload."""
    return cost_price_service.download_template()
