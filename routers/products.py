from typing import List, Optional
from io import BytesIO
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dependencies import (
    get_current_user,
    require_not_analyst,
    require_admin_or_manager,
    require_market_view_roles,
    require_market_manage_roles,
    require_product_upload_roles,
    require_product_create_roles,
)
import models
import schemas
from utils import audit
from utils.pricing import get_current_cost

router = APIRouter(prefix="/products", tags=["Products"])


def _product_name_exists_in_market(
    db: Session,
    product_name: str,
    market_id: Optional[int],
    exclude_product_id: Optional[int] = None,
) -> bool:
    q = db.query(models.Product).filter(
        func.lower(models.Product.product_name) == product_name.strip().lower(),
        models.Product.category_id == market_id,
    )
    if exclude_product_id is not None:
        q = q.filter(models.Product.id != exclude_product_id)
    return db.query(q.exists()).scalar()


def _enrich(product: models.Product, db: Session) -> schemas.ProductOut:
    from utils.s3 import presigned_url as s3_presigned
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
    out.market_id = product.category_id
    out.market = out.category
    out.market_name = out.category.name if out.category else None
    # Convert S3 key to a 1-hour presigned URL for display
    if product.image_url and not product.image_url.startswith("http"):
        try:
            out.image_url = s3_presigned(
                key=product.image_url,
                filename=product.image_url.rsplit("/", 1)[-1],
                content_type="image/jpeg",
                expiry=3600,
            )
        except Exception:
            out.image_url = None
    return out


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), _: models.User = Depends(require_market_view_roles)):
    return db.query(models.ProductCategory).all()


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_market_manage_roles),
):
    if db.query(models.ProductCategory).filter(models.ProductCategory.name == body.name).first():
        raise HTTPException(400, "Category already exists")
    cat = models.ProductCategory(**body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/markets", response_model=List[schemas.MarketOut])
def list_markets(db: Session = Depends(get_db), _: models.User = Depends(require_market_view_roles)):
    return db.query(models.ProductCategory).all()


@router.post("/markets", response_model=schemas.MarketOut, status_code=201)
def create_market(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_market_manage_roles),
):
    if db.query(models.ProductCategory).filter(models.ProductCategory.name == body.name).first():
        raise HTTPException(400, "Market already exists")
    market = models.ProductCategory(**body.model_dump())
    db.add(market)
    db.commit()
    db.refresh(market)
    return market


@router.put("/markets/{market_id}", response_model=schemas.MarketOut)
def update_market(
    market_id: int,
    body: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(market, k, v)
    db.commit()
    db.refresh(market)
    return market


@router.delete("/markets/{market_id}", status_code=204)
def delete_market(
    market_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    db.delete(market)
    db.commit()


@router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: int,
    body: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    cat = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    cat = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    db.delete(cat)
    db.commit()


@router.get("", response_model=List[schemas.ProductOut])
def list_products(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
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
    selected_market = market_id or category_id
    if selected_market:
        q = q.filter(models.Product.category_id == selected_market)
    if is_active is not None:
        q = q.filter(models.Product.is_active == is_active)
    products = q.order_by(models.Product.product_name).offset(skip).limit(limit).all()
    return [_enrich(p, db) for p in products]


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(
    body: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_product_create_roles),
):
    if body.sku and db.query(models.Product).filter(models.Product.sku == body.sku).first():
        raise HTTPException(400, "SKU already exists")
    payload = body.model_dump(exclude_none=True)
    selected_market = payload.pop("market_id", None)
    if selected_market is not None:
        payload["category_id"] = selected_market
    product_name = str(payload.get("product_name") or "").strip()
    market_for_unique = payload.get("category_id")
    if product_name and _product_name_exists_in_market(db, product_name, market_for_unique):
        raise HTTPException(400, "Product name already exists in this market")
    product = models.Product(**payload)
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
    payload = body.model_dump(exclude_none=True)
    selected_market = payload.pop("market_id", None)
    if selected_market is not None:
        payload["category_id"] = selected_market
    next_name = str(payload.get("product_name", p.product_name) or "").strip()
    next_market = payload.get("category_id", p.category_id)
    if next_name and _product_name_exists_in_market(db, next_name, next_market, exclude_product_id=p.id):
        raise HTTPException(400, "Product name already exists in this market")
    old = {k: str(getattr(p, k)) for k in payload}
    for field, value in payload.items():
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


@router.post("/{product_id}/image", response_model=schemas.ProductOut)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    """Upload or replace a product image. Stored in S3 under products/{id}/."""
    import uuid
    from utils.s3 import upload_bytes, presigned_url as s3_presigned

    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")

    ext = (file.filename or "image.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        raise HTTPException(400, "Unsupported image format. Use jpg, png, webp or gif.")

    content = await file.read()
    s3_key = f"products/{product_id}/{uuid.uuid4()}.{ext}"
    content_type = file.content_type or f"image/{ext}"
    upload_bytes(s3_key, content, content_type)

    # Store the S3 key (not the URL) — presigned URL generated on read
    p.image_url = s3_key
    audit.log(db, models.AuditAction.update, models.AuditEntity.product, p.id,
               current_user.id, description=f"Updated image for {p.product_name}")
    db.commit()
    db.refresh(p)
    return _enrich(p, db)


@router.delete("/{product_id}/image", response_model=schemas.ProductOut)
def delete_product_image(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    """Remove the image from a product."""
    from utils.s3 import delete_object

    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")

    if p.image_url:
        delete_object(p.image_url)
        p.image_url = None
        db.commit()
        db.refresh(p)
    return _enrich(p, db)


@router.get("/template")
def download_template(_: models.User = Depends(get_current_user)):
    """Download Excel template for bulk product upload."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(["product_name", "sku", "unit_of_measure", "market_name"])
    ws.append(["Rice 50kg", "RICE-50KG", "Bag", "Abuja"])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=product_template.xlsx"},
    )


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_products(
    file: UploadFile = File(...),
    market_id: Optional[int] = Form(default=None),
    current_user: models.User = Depends(require_product_upload_roles),
):
    """
    Upload an Excel file to S3 and queue parsing via Celery.
    Returns a task_id immediately (< 50 ms). Poll /api/v1/jobs/{task_id} for result.

    Expected columns: product_name, sku (optional), unit_of_measure (optional), market_name (required unless market_id is provided)
    """
    import uuid
    from utils.s3 import upload_bytes
    from utils.tasks import process_product_bulk_task

    content = await file.read()
    s3_key = f"uploads/{uuid.uuid4()}.xlsx"
    upload_bytes(s3_key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    task = process_product_bulk_task.delay(s3_key, current_user.id, market_id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Bulk upload queued. Poll /api/v1/jobs/{task.id} for result.",
    )
