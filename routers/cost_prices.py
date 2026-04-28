from typing import List, Optional
from io import BytesIO
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_not_analyst
import models
import schemas
from utils import audit

router = APIRouter(prefix="/cost-prices", tags=["Cost Prices"])


@router.get("", response_model=List[schemas.CostPriceOut])
def list_cost_prices(
    product_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    cost_price_query = db.query(models.CostPrice)
    if product_id:
        cost_price_query = cost_price_query.filter(models.CostPrice.product_id == product_id)
    return cost_price_query.order_by(models.CostPrice.effective_date.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=schemas.CostPriceOut, status_code=201)
def add_cost_price(
    body: schemas.CostPriceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    product = db.query(models.Product).filter(models.Product.id == body.product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    # Get old price for audit
    old_cp = (
        db.query(models.CostPrice)
        .filter(
            models.CostPrice.product_id == body.product_id,
            models.CostPrice.effective_date <= date.today(),
        )
        .order_by(models.CostPrice.effective_date.desc())
        .first()
    )

    cp = models.CostPrice(
        product_id=body.product_id,
        cost_price=body.cost_price,
        effective_date=body.effective_date,
        notes=body.notes,
        created_by=current_user.id,
    )
    db.add(cp)
    db.flush()
    audit.log(
        db, models.AuditAction.update, models.AuditEntity.cost_price, cp.id,
        current_user.id,
        description=f"Cost price updated for product {product.product_name}",
        old_values={"cost_price": str(old_cp.cost_price)} if old_cp else None,
        new_values={"cost_price": str(body.cost_price), "effective_date": str(body.effective_date)},
    )
    db.commit()
    db.refresh(cp)
    return cp


@router.put("/{cp_id}", response_model=schemas.CostPriceOut)
def update_cost_price(
    cp_id: int,
    body: schemas.CostPriceUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    cp = db.query(models.CostPrice).filter(models.CostPrice.id == cp_id).first()
    if not cp:
        raise HTTPException(404, "Cost price record not found")
    old = {"cost_price": str(cp.cost_price), "effective_date": str(cp.effective_date)}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cp, field, value)
    audit.log(db, models.AuditAction.update, models.AuditEntity.cost_price, cp.id,
               current_user.id, old_values=old,
               new_values=body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(cp)
    return cp


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_cost_prices(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_not_analyst),
):
    """
    Upload an Excel file to S3 and queue parsing via Celery.
    Returns a task_id immediately (< 50 ms). Poll /api/v1/jobs/{task_id} for result.

    Required columns: product_name, uom, market_name, cost_price
    Effective date is applied immediately (today).
    """
    import uuid
    from utils.s3 import upload_bytes
    from utils.tasks import process_cost_price_bulk_task

    content = await file.read()
    s3_key = f"uploads/{uuid.uuid4()}.xlsx"
    upload_bytes(s3_key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    task = process_cost_price_bulk_task.delay(s3_key, current_user.id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Bulk upload queued. Poll /api/v1/jobs/{task.id} for result.",
    )


@router.get("/template")
def download_template(_: models.User = Depends(get_current_user)):
    """Download Excel template for bulk cost price upload."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cost Prices"
    ws.append(["product_name", "uom", "market_name", "cost_price"])
    ws.append(["Rice 50kg", "Bag", "Abuja", 100000])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cost_price_template.xlsx"},
    )
