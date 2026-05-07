"""Customer domain."""

from typing import List, Optional
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, String

import models
import schemas
from utils import audit


def _not_cancelled_invoice_filter():
    return func.lower(models.Invoice.status.cast(String)) != "cancelled"


def list_customers(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[schemas.CustomerOut]:
    last_order_sq = (
        db.query(
            models.Invoice.customer_id.label("customer_id"),
            func.max(models.Invoice.invoice_date).label("last_date"),
        )
        .filter(_not_cancelled_invoice_filter())
        .group_by(models.Invoice.customer_id)
        .subquery()
    )

    customer_query = db.query(models.Customer, last_order_sq.c.last_date).outerjoin(
        last_order_sq, models.Customer.id == last_order_sq.c.customer_id
    )
    if search:
        term = f"%{search}%"
        customer_query = customer_query.filter(
            models.Customer.customer_name.ilike(term)
            | models.Customer.business_name.ilike(term)
            | models.Customer.phone.ilike(term)
            | models.Customer.email.ilike(term)
        )
    if category:
        customer_query = customer_query.filter(models.Customer.category == category)
    if is_active is not None:
        customer_query = customer_query.filter(models.Customer.is_active == is_active)

    rows = customer_query.order_by(models.Customer.customer_name).offset(skip).limit(limit).all()

    results = []
    for customer, last_date in rows:
        data = schemas.CustomerOut.model_validate(customer).model_dump()
        data["last_order_date"] = last_date
        results.append(schemas.CustomerOut(**data))
    return results


def create_customer(db: Session, body: schemas.CustomerCreate, current_user: models.User) -> models.Customer:
    customer = models.Customer(**body.model_dump())
    db.add(customer)
    db.flush()
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.customer,
        customer.id,
        current_user.id,
        description=f"Created customer {customer.customer_name}",
    )
    db.commit()
    db.refresh(customer)
    return customer


def get_customer(db: Session, customer_id: int) -> models.Customer:
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


def update_customer(
    db: Session, customer_id: int, body: schemas.CustomerUpdate, current_user: models.User
) -> models.Customer:
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    old = {k: str(getattr(c, k)) for k in body.model_dump(exclude_none=True)}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.customer,
        c.id,
        current_user.id,
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(c)
    return c


def deactivate_customer(db: Session, customer_id: int, current_user: models.User) -> schemas.MessageResponse:
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    c.is_active = False
    audit.log(
        db,
        models.AuditAction.deactivate,
        models.AuditEntity.customer,
        c.id,
        current_user.id,
        description=f"Deactivated customer {c.customer_name}",
    )
    db.commit()
    return schemas.MessageResponse(message="Customer deactivated")


def customer_quotations(
    db: Session, customer_id: int, skip: int = 0, limit: int = 20
) -> List[models.Quotation]:
    return (
        db.query(models.Quotation)
        .filter(models.Quotation.customer_id == customer_id)
        .order_by(models.Quotation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def customer_invoices(
    db: Session,
    customer_id: int,
    skip: int = 0,
    limit: int = 200,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[models.Invoice]:
    invoice_query = db.query(models.Invoice).filter(models.Invoice.customer_id == customer_id)
    if date_from:
        invoice_query = invoice_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        invoice_query = invoice_query.filter(models.Invoice.invoice_date <= date_to)
    return invoice_query.order_by(models.Invoice.created_at.desc()).offset(skip).limit(limit).all()


def customer_analytics(db: Session, customer_id: int) -> schemas.CustomerDetailOut:
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    base_filter = [
        models.Invoice.customer_id == customer_id,
        _not_cancelled_invoice_filter(),
    ]

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

    item_agg = (
        db.query(
            func.sum(models.InvoiceItem.quantity).label("total_qty"),
            func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity).label("cost_of_sales"),
        )
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(*base_filter)
        .one()
    )

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

    num_orders = int(inv_agg.num_orders or 0)
    total_value = float(inv_agg.total_value or 0)
    total_qty = float(item_agg.total_qty or 0)
    cos = float(item_agg.cost_of_sales or 0)
    avg_order = total_value / num_orders if num_orders else 0
    pref_pt = None
    if pt_rows:
        payment_term_value = max(pt_rows, key=lambda row: row.cnt).payment_term
        pref_pt = (
            payment_term_value.value
            if hasattr(payment_term_value, "value")
            else (str(payment_term_value) if payment_term_value is not None else None)
        )
    pref_dt = None
    if dt_rows:
        raw_delivery = max(dt_rows, key=lambda r: r.cnt).delivery_type
        pref_dt = raw_delivery.value if hasattr(raw_delivery, "value") else str(raw_delivery)

    base = schemas.CustomerOut.model_validate(c).model_dump(exclude={"last_order_date"})
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


def customer_top_products(
    db: Session,
    customer_id: int,
    limit: int = 10,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[dict]:
    product_sales_query = (
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
            _not_cancelled_invoice_filter(),
        )
    )
    if date_from:
        product_sales_query = product_sales_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        product_sales_query = product_sales_query.filter(models.Invoice.invoice_date <= date_to)
    rows = (
        product_sales_query.group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": product_row.id,
            "product_name": product_row.product_name,
            "total_qty": float(product_row.total_qty),
            "total_value": float(product_row.total_value),
        }
        for product_row in rows
    ]


def customer_cost_of_sales(
    db: Session,
    customer_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict:
    c = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")

    base_filter = [
        models.Invoice.customer_id == customer_id,
        _not_cancelled_invoice_filter(),
    ]
    if date_from:
        base_filter.append(models.Invoice.invoice_date >= date_from)
    if date_to:
        base_filter.append(models.Invoice.invoice_date <= date_to)

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

    total_cost = sum(float(product_row.cost or 0) for product_row in product_rows)
    total_revenue = sum(float(product_row.revenue or 0) for product_row in product_rows)
    gross_profit = total_revenue - total_cost
    gross_margin = round(gross_profit / total_revenue * 100, 2) if total_revenue else 0

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
                "product_id": product_row.product_id,
                "product_name": product_row.product_name,
                "qty": float(product_row.qty or 0),
                "cost": float(product_row.cost or 0),
                "revenue": float(product_row.revenue or 0),
                "gross_profit": float(product_row.revenue or 0) - float(product_row.cost or 0),
                "margin_pct": round(
                    (float(product_row.revenue or 0) - float(product_row.cost or 0))
                    / float(product_row.revenue)
                    * 100,
                    2,
                )
                if product_row.revenue
                else 0,
            }
            for product_row in product_rows
        ],
        "by_invoice": [
            {
                "invoice_id": invoice_row.id,
                "invoice_number": invoice_row.invoice_number,
                "invoice_date": str(invoice_row.invoice_date),
                "cost": float(invoice_row.cost or 0),
                "revenue": float(invoice_row.revenue or 0),
                "gross_profit": float(invoice_row.revenue or 0) - float(invoice_row.cost or 0),
                "margin_pct": round(
                    (float(invoice_row.revenue or 0) - float(invoice_row.cost or 0))
                    / float(invoice_row.revenue)
                    * 100,
                    2,
                )
                if invoice_row.revenue
                else 0,
            }
            for invoice_row in invoice_rows
        ],
    }
