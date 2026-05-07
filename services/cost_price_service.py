"""Cost price domain."""

from io import BytesIO
from typing import List, Optional
from datetime import date

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit
from services.integrations.storage import upload_bytes
from services.integrations.tasks import process_cost_price_bulk_task


def list_cost_prices(
    db: Session, product_id: Optional[int] = None, skip: int = 0, limit: int = 100
) -> List[models.CostPrice]:
    cost_price_query = db.query(models.CostPrice)
    if product_id:
        cost_price_query = cost_price_query.filter(models.CostPrice.product_id == product_id)
    return cost_price_query.order_by(models.CostPrice.effective_date.desc()).offset(skip).limit(limit).all()


def add_cost_price(db: Session, body: schemas.CostPriceCreate, current_user: models.User) -> models.CostPrice:
    product = db.query(models.Product).filter(models.Product.id == body.product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

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
        db,
        models.AuditAction.update,
        models.AuditEntity.cost_price,
        cp.id,
        current_user.id,
        description=f"Cost price updated for product {product.product_name}",
        old_values={"cost_price": str(old_cp.cost_price)} if old_cp else None,
        new_values={"cost_price": str(body.cost_price), "effective_date": str(body.effective_date)},
    )
    db.commit()
    db.refresh(cp)
    return cp


def update_cost_price(
    db: Session, cp_id: int, body: schemas.CostPriceUpdate, current_user: models.User
) -> models.CostPrice:
    cp = db.query(models.CostPrice).filter(models.CostPrice.id == cp_id).first()
    if not cp:
        raise HTTPException(404, "Cost price record not found")
    old = {"cost_price": str(cp.cost_price), "effective_date": str(cp.effective_date)}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cp, field, value)
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.cost_price,
        cp.id,
        current_user.id,
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(cp)
    return cp


async def bulk_upload_cost_prices(file: UploadFile, current_user: models.User) -> schemas.JobEnqueuedResponse:
    import uuid

    content = await file.read()
    s3_key = f"uploads/{uuid.uuid4()}.xlsx"
    upload_bytes(s3_key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    task = process_cost_price_bulk_task.delay(s3_key, current_user.id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Bulk upload queued. Poll /api/v1/jobs/{task.id} for result.",
    )


def download_template() -> StreamingResponse:
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
