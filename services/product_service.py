"""Product domain service layer."""

from typing import List, Optional
from io import BytesIO
from datetime import date
import re

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

import models
import schemas
from utils import audit


def _product_name_exists_in_market(
    db: Session,
    product_name: str,
    market_id: Optional[int],
    exclude_product_id: Optional[int] = None,
) -> bool:
    existing_product_query = db.query(models.Product).filter(
        func.lower(models.Product.product_name) == product_name.strip().lower(),
        models.Product.category_id == market_id,
    )
    if exclude_product_id is not None:
        existing_product_query = existing_product_query.filter(models.Product.id != exclude_product_id)
    return db.query(existing_product_query.exists()).scalar()


def _generate_unique_sku(db: Session, product_name: str, market_id: Optional[int]) -> str:
    base_name = re.sub(r"[^A-Z0-9]+", "-", (product_name or "").upper()).strip("-")
    if not base_name:
        base_name = "PRODUCT"
    base_name = base_name[:24]
    market_part = f"M{market_id}" if market_id else "M0"
    counter = 1
    while True:
        candidate = f"{base_name}-{market_part}-{counter:03d}"
        exists = db.query(models.Product).filter(models.Product.sku == candidate).first()
        if not exists:
            return candidate
        counter += 1


def _batch_latest_costs(db: Session, product_ids: List[int]) -> dict[int, models.CostPrice]:
    if not product_ids:
        return {}
    today = date.today()
    subq = (
        db.query(
            models.CostPrice.product_id.label("pid"),
            func.max(models.CostPrice.effective_date).label("mx"),
        )
        .filter(
            models.CostPrice.product_id.in_(product_ids),
            models.CostPrice.effective_date <= today,
        )
        .group_by(models.CostPrice.product_id)
        .subquery()
    )
    rows = (
        db.query(models.CostPrice)
        .join(
            subq,
            and_(
                models.CostPrice.product_id == subq.c.pid,
                models.CostPrice.effective_date == subq.c.mx,
            ),
        )
        .all()
    )
    by_pid: dict[int, models.CostPrice] = {}
    for cp in rows:
        if cp.product_id not in by_pid:
            by_pid[cp.product_id] = cp
    return by_pid


def enrich_product(
    product: models.Product,
    db: Session,
    *,
    cost_by_product: Optional[dict[int, models.CostPrice]] = None,
) -> schemas.ProductOut:
    from utils.s3 import presigned_url as s3_presigned

    out = schemas.ProductOut.model_validate(product)
    if cost_by_product is not None:
        cp = cost_by_product.get(product.id)
    else:
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


def list_categories(db: Session, current_user: models.User) -> List[models.ProductCategory]:
    market_query = db.query(models.ProductCategory)
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        market_query = market_query.filter(models.ProductCategory.is_active == True)
    return market_query.all()


def create_category(db: Session, body: schemas.CategoryCreate) -> models.ProductCategory:
    if db.query(models.ProductCategory).filter(models.ProductCategory.name == body.name).first():
        raise HTTPException(400, "Category already exists")
    cat = models.ProductCategory(**body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def list_markets(db: Session, current_user: models.User) -> List[models.ProductCategory]:
    market_query = db.query(models.ProductCategory)
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        market_query = market_query.filter(models.ProductCategory.is_active == True)
    return market_query.all()


def create_market(db: Session, body: schemas.CategoryCreate) -> models.ProductCategory:
    if db.query(models.ProductCategory).filter(models.ProductCategory.name == body.name).first():
        raise HTTPException(400, "Market already exists")
    market = models.ProductCategory(**body.model_dump())
    db.add(market)
    db.commit()
    db.refresh(market)
    return market


def update_market(db: Session, market_id: int, body: schemas.CategoryUpdate) -> models.ProductCategory:
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(market, k, v)
    db.commit()
    db.refresh(market)
    return market


def delete_market(db: Session, market_id: int) -> None:
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    db.delete(market)
    db.commit()


def disable_market(db: Session, market_id: int) -> models.ProductCategory:
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    market.is_active = False
    db.commit()
    db.refresh(market)
    return market


def enable_market(db: Session, market_id: int) -> models.ProductCategory:
    market = db.query(models.ProductCategory).filter(models.ProductCategory.id == market_id).first()
    if not market:
        raise HTTPException(404, "Market not found")
    market.is_active = True
    db.commit()
    db.refresh(market)
    return market


def update_category(db: Session, category_id: int, body: schemas.CategoryUpdate) -> models.ProductCategory:
    cat = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


def delete_category(db: Session, category_id: int) -> None:
    cat = db.query(models.ProductCategory).filter(models.ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    db.delete(cat)
    db.commit()


def list_products(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = False,
) -> schemas.ProductListPage:
    skip = max(skip, 0)
    limit = min(max(limit, 1), 200)

    product_query = db.query(models.Product)
    if search:
        term = f"%{search}%"
        product_query = product_query.filter(
            models.Product.product_name.ilike(term) | models.Product.sku.ilike(term)
        )
    selected_market = market_id or category_id
    if selected_market:
        product_query = product_query.filter(models.Product.category_id == selected_market)
    if include_inactive:
        if is_active is not None:
            product_query = product_query.filter(models.Product.is_active == is_active)
    else:
        product_query = product_query.filter(models.Product.is_active == True)

    total = product_query.order_by(None).count()
    products = product_query.order_by(models.Product.product_name).offset(skip).limit(limit).all()
    cost_map = _batch_latest_costs(db, [p.id for p in products])
    items = [enrich_product(p, db, cost_by_product=cost_map) for p in products]
    return schemas.ProductListPage(total=total, skip=skip, limit=limit, items=items)


def create_product(db: Session, body: schemas.ProductCreate, current_user: models.User) -> schemas.ProductOut:
    payload = body.model_dump(exclude_none=True)
    selected_market = payload.pop("market_id", None)
    if selected_market is not None:
        payload["category_id"] = selected_market
    if payload.get("sku") and db.query(models.Product).filter(models.Product.sku == payload["sku"]).first():
        raise HTTPException(400, "SKU already exists")
    product_name = str(payload.get("product_name") or "").strip()
    market_for_unique = payload.get("category_id")
    if product_name and _product_name_exists_in_market(db, product_name, market_for_unique):
        existing = db.query(models.Product).filter(
            func.lower(models.Product.product_name) == product_name.lower(),
            models.Product.category_id == market_for_unique,
        ).first()
        if existing:
            if payload.get("sku"):
                existing.sku = payload["sku"]
            if payload.get("unit_of_measure"):
                existing.unit_of_measure = payload["unit_of_measure"]
            db.commit()
            db.refresh(existing)
            return enrich_product(existing, db)
    if not payload.get("sku"):
        payload["sku"] = _generate_unique_sku(db, product_name, market_for_unique)
    product = models.Product(**payload)
    db.add(product)
    db.flush()
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.product,
        product.id,
        current_user.id,
        description=f"Created product {product.product_name}",
    )
    db.commit()
    db.refresh(product)
    return enrich_product(product, db)


def get_product(db: Session, product_id: int) -> schemas.ProductOut:
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    return enrich_product(p, db)


def list_product_variants(db: Session, product_id: int) -> List[schemas.ProductVariantOut]:
    anchor = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not anchor:
        raise HTTPException(404, "Product not found")
    name_key = anchor.product_name.strip().lower()
    rows = (
        db.query(models.Product)
        .filter(
            models.Product.category_id == anchor.category_id,
            func.lower(models.Product.product_name) == name_key,
            models.Product.is_active == True,
        )
        .order_by(func.coalesce(models.Product.unit_of_measure, ""))
        .all()
    )
    return [
        schemas.ProductVariantOut(
            id=p.id,
            product_name=p.product_name,
            unit_of_measure=p.unit_of_measure,
            sku=p.sku,
        )
        for p in rows
    ]


def update_product(
    db: Session, product_id: int, body: schemas.ProductUpdate, current_user: models.User
) -> schemas.ProductOut:
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
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.product,
        p.id,
        current_user.id,
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(p)
    return enrich_product(p, db)


def disable_product(db: Session, product_id: int, current_user: models.User) -> schemas.MessageResponse:
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    p.is_active = False
    audit.log(
        db,
        models.AuditAction.deactivate,
        models.AuditEntity.product,
        p.id,
        current_user.id,
        description=f"Deactivated product {p.product_name}",
    )
    db.commit()
    return schemas.MessageResponse(message="Product disabled")


def enable_product(db: Session, product_id: int, current_user: models.User) -> schemas.MessageResponse:
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    p.is_active = True
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.product,
        p.id,
        current_user.id,
        description=f"Enabled product {p.product_name}",
    )
    db.commit()
    return schemas.MessageResponse(message="Product enabled")


def delete_product(db: Session, product_id: int, current_user: models.User) -> schemas.MessageResponse:
    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")
    name = p.product_name

    linked_quotation_items = (
        db.query(func.count(models.QuotationItem.id)).filter(models.QuotationItem.product_id == p.id).scalar() or 0
    )
    linked_invoice_items = (
        db.query(func.count(models.InvoiceItem.id)).filter(models.InvoiceItem.product_id == p.id).scalar() or 0
    )

    if linked_quotation_items or linked_invoice_items:
        p.is_active = False
        audit.log(
            db,
            models.AuditAction.deactivate,
            models.AuditEntity.product,
            product_id,
            current_user.id,
            description=f"Deactivated product {name} (linked to quotations or invoices)",
            new_values={
                "is_active": False,
                "linked_quotation_items": linked_quotation_items,
                "linked_invoice_items": linked_invoice_items,
            },
        )
        db.commit()
        return schemas.MessageResponse(
            message="Product is used in existing records and was disabled instead of deleted"
        )

    removed_cost_prices = db.query(models.CostPrice).filter(models.CostPrice.product_id == p.id).delete(
        synchronize_session=False
    )

    audit.log(
        db,
        models.AuditAction.delete,
        models.AuditEntity.product,
        product_id,
        current_user.id,
        description=(
            f"Deleted product {name}"
            + (f" ({removed_cost_prices} cost price row(s) removed)" if removed_cost_prices else "")
        ),
        new_values={"cost_price_rows_removed": removed_cost_prices} if removed_cost_prices else None,
    )
    db.delete(p)
    db.commit()
    return schemas.MessageResponse(message="Product deleted")


def product_cost_history(db: Session, product_id: int) -> List[models.CostPrice]:
    return (
        db.query(models.CostPrice)
        .filter(models.CostPrice.product_id == product_id)
        .order_by(models.CostPrice.effective_date.desc())
        .all()
    )


def product_analytics(db: Session, product_id: int) -> schemas.ProductAnalyticsOut:
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
    unique_customers = len(
        {
            inv.customer_id
            for inv in db.query(models.Invoice)
            .join(models.InvoiceItem)
            .filter(models.InvoiceItem.product_id == product_id)
            .all()
        }
    )

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
            {
                "customer_id": r.id,
                "customer_name": r.customer_name,
                "total_qty": float(r.qty),
                "total_value": float(r.value),
            }
            for r in top_rows
        ],
        monthly_trend=[],
    )


async def upload_product_image(
    db: Session, product_id: int, file: UploadFile, current_user: models.User
) -> schemas.ProductOut:
    import uuid
    from utils.s3 import upload_bytes

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

    p.image_url = s3_key
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.product,
        p.id,
        current_user.id,
        description=f"Updated image for {p.product_name}",
    )
    db.commit()
    db.refresh(p)
    return enrich_product(p, db)


def delete_product_image(db: Session, product_id: int) -> schemas.ProductOut:
    from utils.s3 import delete_object

    p = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not p:
        raise HTTPException(404, "Product not found")

    if p.image_url:
        delete_object(p.image_url)
        p.image_url = None
        db.commit()
        db.refresh(p)
    return enrich_product(p, db)


def download_template() -> StreamingResponse:
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


async def bulk_upload_products(
    file: UploadFile, current_user: models.User, market_id: Optional[int] = None
) -> schemas.JobEnqueuedResponse:
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
