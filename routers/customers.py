from typing import List, Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dependencies import get_current_user, require_not_analyst
import models
import schemas
from utils import audit

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=List[schemas.CustomerOut])
def list_customers(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    # Subquery: last active invoice date per customer
    last_order_sq = (
        db.query(
            models.Invoice.customer_id.label("cid"),
            func.max(models.Invoice.invoice_date).label("last_date"),
        )
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
        .group_by(models.Invoice.customer_id)
        .subquery()
    )

    q = (
        db.query(models.Customer, last_order_sq.c.last_date)
        .outerjoin(last_order_sq, models.Customer.id == last_order_sq.c.cid)
    )
    if search:
        term = f"%{search}%"
        q = q.filter(
            models.Customer.customer_name.ilike(term)
            | models.Customer.business_name.ilike(term)
            | models.Customer.phone.ilike(term)
            | models.Customer.email.ilike(term)
        )
    if category:
        q = q.filter(models.Customer.category == category)
    if is_active is not None:
        q = q.filter(models.Customer.is_active == is_active)

    rows = q.order_by(models.Customer.customer_name).offset(skip).limit(limit).all()

    results = []
    for customer, last_date in rows:
        data = schemas.CustomerOut.model_validate(customer).model_dump()
        data["last_order_date"] = last_date
        results.append(schemas.CustomerOut(**data))
    return results


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(
    body: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    customer = models.Customer(**body.model_dump())
    db.add(customer)
    db.flush()
    audit.log(db, models.AuditAction.create, models.AuditEntity.customer, customer.id,
               current_user.id, description=f"Created customer {customer.customer_name}")
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(
    customer_id: int,
    body: schemas.CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    old = {k: str(getattr(c, k)) for k in body.model_dump(exclude_none=True)}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    audit.log(db, models.AuditAction.update, models.AuditEntity.customer, c.id,
               current_user.id, old_values=old,
               new_values=body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{customer_id}", response_model=schemas.MessageResponse)
def deactivate_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    c.is_active = False
    audit.log(db, models.AuditAction.deactivate, models.AuditEntity.customer, c.id,
               current_user.id, description=f"Deactivated customer {c.customer_name}")
    db.commit()
    return schemas.MessageResponse(message="Customer deactivated")


@router.get("/{customer_id}/quotations", response_model=List[schemas.QuotationOut])
def customer_quotations(
    customer_id: int,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Quotation)
        .filter(models.Quotation.customer_id == customer_id)
        .order_by(models.Quotation.created_at.desc())
        .offset(skip).limit(limit).all()
    )


@router.get("/{customer_id}/invoices", response_model=List[schemas.InvoiceOut])
def customer_invoices(
    customer_id: int,
    skip: int = 0,
    limit: int = 200,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Invoice).filter(models.Invoice.customer_id == customer_id)
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    return q.order_by(models.Invoice.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{customer_id}/analytics", response_model=schemas.CustomerDetailOut)
def customer_analytics(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    base_filter = [
        models.Invoice.customer_id == customer_id,
        models.Invoice.status != models.InvoiceStatus.cancelled,
    ]

    # Aggregate invoice/item stats in one query using line totals (source of truth).
    inv_agg = (
        db.query(
            func.count(func.distinct(models.Invoice.id)).label("num_orders"),
            func.sum(models.InvoiceItem.line_total).label("total_value"),
            func.max(models.Invoice.invoice_date).label("last_order"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(*base_filter)
        .one()
    )

    # Aggregate item-level stats in one query
    item_agg = (
        db.query(
            func.sum(models.InvoiceItem.quantity).label("total_qty"),
            func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity).label("cost_of_sales"),
        )
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(*base_filter)
        .one()
    )

    # Payment term + delivery type frequency
    pt_rows = (
        db.query(models.Invoice.payment_term, func.count(models.Invoice.id).label("cnt"))
        .filter(*base_filter)
        .group_by(models.Invoice.payment_term)
        .all()
    )
    dt_rows = (
        db.query(models.Invoice.delivery_type, func.count(models.Invoice.id).label("cnt"))
        .filter(*base_filter)
        .group_by(models.Invoice.delivery_type)
        .all()
    )

    num_orders  = int(inv_agg.num_orders or 0)
    total_value = float(inv_agg.total_value or 0)
    total_qty   = float(item_agg.total_qty or 0)
    cos         = float(item_agg.cost_of_sales or 0)
    avg_order   = total_value / num_orders if num_orders else 0
    pref_pt     = max(pt_rows, key=lambda r: r.cnt).payment_term if pt_rows else None
    pref_dt = None
    if dt_rows:
        raw_delivery = max(dt_rows, key=lambda r: r.cnt).delivery_type
        # Backward compatibility: older rows/environments may return plain string.
        pref_dt = raw_delivery.value if hasattr(raw_delivery, "value") else str(raw_delivery)

    base = schemas.CustomerOut.model_validate(c).model_dump()
    return schemas.CustomerDetailOut(
        **base,
        total_sales_value=total_value,
        total_quantity_bought=total_qty,
        total_orders=num_orders,
        average_order_value=avg_order,
        last_order_date=inv_agg.last_order,
        preferred_payment_term=pref_pt,
        preferred_delivery_type=pref_dt,
        cost_of_sales=cos,
    )


@router.get("/{customer_id}/top-products")
def customer_top_products(
    customer_id: int,
    limit: int = 10,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = (
        db.query(
            models.Product.id,
            models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("total_qty"),
            func.sum(models.InvoiceItem.line_total).label("total_value"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(
            models.Invoice.customer_id == customer_id,
            models.Invoice.status != models.InvoiceStatus.cancelled,
        )
    )
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    rows = (
        q.group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {"product_id": r.id, "product_name": r.product_name,
         "total_qty": float(r.total_qty), "total_value": float(r.total_value)}
        for r in rows
    ]


@router.get("/{customer_id}/cost-of-sales")
def customer_cost_of_sales(
    customer_id: int,
    date_from: Optional[date] = None,
    date_to:   Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    base_filter = [
        models.Invoice.customer_id == customer_id,
        models.Invoice.status != models.InvoiceStatus.cancelled,
    ]
    if date_from:
        base_filter.append(models.Invoice.invoice_date >= date_from)
    if date_to:
        base_filter.append(models.Invoice.invoice_date <= date_to)

    # Product breakdown
    product_rows = (
        db.query(
            models.Product.id.label("product_id"),
            models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity).label("cost"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(*base_filter)
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity).desc())
        .all()
    )

    # Invoice breakdown
    invoice_rows = (
        db.query(
            models.Invoice.id,
            models.Invoice.invoice_number,
            models.Invoice.invoice_date,
            func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity).label("cost"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(*base_filter)
        .group_by(models.Invoice.id, models.Invoice.invoice_number, models.Invoice.invoice_date)
        .order_by(models.Invoice.invoice_date.desc())
        .all()
    )

    total_cost    = sum(float(r.cost or 0)    for r in product_rows)
    total_revenue = sum(float(r.revenue or 0) for r in product_rows)
    gross_profit  = total_revenue - total_cost
    gross_margin  = round(gross_profit / total_revenue * 100, 2) if total_revenue else 0

    return {
        "customer_name": c.customer_name,
        "summary": {
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin,
        },
        "by_product": [
            {
                "product_id": r.product_id,
                "product_name": r.product_name,
                "qty": float(r.qty or 0),
                "cost": float(r.cost or 0),
                "revenue": float(r.revenue or 0),
                "gross_profit": float(r.revenue or 0) - float(r.cost or 0),
                "margin_pct": round(
                    (float(r.revenue or 0) - float(r.cost or 0)) / float(r.revenue) * 100, 2
                ) if r.revenue else 0,
            }
            for r in product_rows
        ],
        "by_invoice": [
            {
                "invoice_id": r.id,
                "invoice_number": r.invoice_number,
                "invoice_date": str(r.invoice_date),
                "cost": float(r.cost or 0),
                "revenue": float(r.revenue or 0),
                "gross_profit": float(r.revenue or 0) - float(r.cost or 0),
                "margin_pct": round(
                    (float(r.revenue or 0) - float(r.cost or 0)) / float(r.revenue) * 100, 2
                ) if r.revenue else 0,
            }
            for r in invoice_rows
        ],
    }
