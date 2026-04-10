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
        .filter(models.Invoice.status == models.InvoiceStatus.active)
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

    invoices = (
        db.query(models.Invoice)
        .filter(
            models.Invoice.customer_id == customer_id,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .all()
    )

    total_value = sum(float(inv.total_amount) for inv in invoices)
    total_qty = sum(
        float(item.quantity)
        for inv in invoices
        for item in inv.items
    )
    # Cost of sales = sum(cost_price * quantity) for all invoice items
    cost_of_sales = sum(
        float(item.cost_price) * float(item.quantity)
        for inv in invoices
        for item in inv.items
    )
    num_orders = len(invoices)
    avg_order = total_value / num_orders if num_orders else 0
    last_order = max((inv.invoice_date for inv in invoices), default=None)

    # payment term frequency
    pt_counts: dict = {}
    dt_counts: dict = {}
    for inv in invoices:
        pt_counts[inv.payment_term] = pt_counts.get(inv.payment_term, 0) + 1
        dt_counts[inv.delivery_type.value] = dt_counts.get(inv.delivery_type.value, 0) + 1

    pref_pt = max(pt_counts, key=pt_counts.get) if pt_counts else None
    pref_dt = max(dt_counts, key=dt_counts.get) if dt_counts else None

    base = schemas.CustomerOut.model_validate(c).model_dump()
    out = schemas.CustomerDetailOut(
        **base,
        total_sales_value=total_value,
        total_quantity_bought=total_qty,
        total_orders=num_orders,
        average_order_value=avg_order,
        last_order_date=last_order,
        preferred_payment_term=pref_pt,
        preferred_delivery_type=pref_dt,
        cost_of_sales=cost_of_sales,
    )
    return out


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
            models.Invoice.status == models.InvoiceStatus.active,
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
