from typing import List, Optional
from io import BytesIO
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dependencies import get_current_user, require_not_analyst, require_admin_or_manager
import models
import schemas
from utils import audit
from utils.pricing import get_current_cost

router = APIRouter(prefix="/products", tags=["Products"])


def _enrich(product: models.Product, db: Session) -> schemas.ProductOut:
    out = schemas.ProductOut.model_validate(product)
    cp = (
        db.query(models.CostPrice)
        .filter(
            models.CostPrice.product_id == product.id,
            models.CostPrice.effective_date <= date.today(),
        )
        .order_by(models.CostPrice.effective_date.desc())
        .first()
    )
    if cp:
        out.current_cost_price = float(cp.cost_price)
        out.cost_price_effective_date = cp.effective_date
    return out


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.ProductCategory).all()


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    if db.query(models.ProductCategory).filter(models.ProductCategory.name == body.name).first():
        raise HTTPException(400, "Category already exists")
    cat = models.ProductCategory(**body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("", response_model=List[schemas.ProductOut])
def list_products(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Product)
    if search:
        term = f"%{search}%"
        q = q.filter(
            models.Product.product_name.ilike(term) | models.Product.sku.ilike(term)
        )
    if category_id:
        q = q.filter(models.Product.category_id == category_id)
    if is_active is not None:
        q = q.filter(models.Product.is_active == is_active)
    products = q.order_by(models.Product.product_name).offset(skip).limit(limit).all()
    return [_enrich(p, db) for p in products]


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(
    body: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    if body.sku and db.query(models.Product).filter(models.Product.sku == body.sku).first():
        raise HTTPException(400, "SKU already exists")
    product = models.Product(**body.model_dump())
    db.add(product)
    db.flush()
    audit.log(db, models.AuditAction.create, models.AuditEntity.product, product.id,
               current_user.id, description=f"Created product {product.product_name}")
    db.commit()
    db.refresh(product)
    return _enrich(product, db)


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    return _enrich(p, db)


@router.put("/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: int,
    body: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    old = {k: str(getattr(p, k)) for k in body.model_dump(exclude_none=True)}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(p, field, value)
    audit.log(db, models.AuditAction.update, models.AuditEntity.product, p.id,
               current_user.id, old_values=old, new_values=body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(p)
    return _enrich(p, db)


@router.delete("/{product_id}", response_model=schemas.MessageResponse)
def deactivate_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    p.is_active = False
    audit.log(db, models.AuditAction.deactivate, models.AuditEntity.product, p.id,
               current_user.id, description=f"Deactivated product {p.product_name}")
    db.commit()
    return schemas.MessageResponse(message="Product deactivated")


@router.get("/{product_id}/cost-history", response_model=List[schemas.CostPriceOut])
def product_cost_history(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.CostPrice)
        .filter(models.CostPrice.product_id == product_id)
        .order_by(models.CostPrice.effective_date.desc())
        .all()
    )


@router.get("/{product_id}/analytics", response_model=schemas.ProductAnalyticsOut)
def product_analytics(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")

    items = (
        db.query(models.InvoiceItem)
        .join(models.Invoice)
        .filter(
            models.InvoiceItem.product_id == product_id,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .all()
    )

    total_qty = sum(float(i.quantity) for i in items)
    total_revenue = sum(float(i.line_total) for i in items)
    unique_invoices = len({i.invoice_id for i in items})
    unique_customers = len({
        inv.customer_id
        for inv in db.query(models.Invoice)
        .join(models.InvoiceItem)
        .filter(models.InvoiceItem.product_id == product_id)
        .all()
    })

    # Top customers
    top_rows = (
        db.query(
            models.Customer.id,
            models.Customer.customer_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(models.InvoiceItem.line_total).label("value"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(
            models.InvoiceItem.product_id == product_id,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10)
        .all()
    )

    return schemas.ProductAnalyticsOut(
        product_id=product_id,
        product_name=p.product_name,
        total_quantity_sold=total_qty,
        total_revenue=total_revenue,
        total_customers=unique_customers,
        total_invoices=unique_invoices,
        top_customers=[
            {"customer_id": r.id, "customer_name": r.customer_name,
             "total_qty": float(r.qty), "total_value": float(r.value)}
            for r in top_rows
        ],
        monthly_trend=[],  # populated via analytics endpoint for date filtering
    )


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_products(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_not_analyst),
):
    """
    Save the uploaded Excel to disk and queue parsing via Celery.
    Returns a task_id immediately (< 50 ms). Poll /api/v1/jobs/{task_id} for result.

    Expected columns: product_name, sku (optional), unit_of_measure (optional), category_name (optional)
    """
    import os
    import uuid
    from utils.tasks import process_product_bulk_task, JOB_INPUT_DIR

    os.makedirs(JOB_INPUT_DIR, exist_ok=True)
    dest = os.path.join(JOB_INPUT_DIR, f"{uuid.uuid4()}.xlsx")
    content = await file.read()
    with open(dest, "wb") as fh:
        fh.write(content)

    task = process_product_bulk_task.delay(dest, current_user.id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Bulk upload queued. Poll /api/v1/jobs/{task.id} for result.",
    )
