from datetime import date, timedelta, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from database import get_db
from dependencies import get_current_user
import models
import schemas

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _sales_in_range(db: Session, start: date, end: date) -> float:
    result = (
        db.query(func.sum(models.Invoice.total_amount))
        .filter(
            models.Invoice.invoice_date >= start,
            models.Invoice.invoice_date <= end,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .scalar()
    )
    return float(result or 0)


@router.get("/overview", response_model=schemas.DashboardOverview)
def overview(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Counts today
    quotations_today = (
        db.query(func.count(models.Quotation.id))
        .filter(models.Quotation.quotation_date == today)
        .scalar() or 0
    )
    invoices_today = (
        db.query(func.count(models.Invoice.id))
        .filter(models.Invoice.invoice_date == today,
                models.Invoice.status == models.InvoiceStatus.active)
        .scalar() or 0
    )

    sales_today = _sales_in_range(db, today, today)
    sales_week = _sales_in_range(db, week_start, today)
    sales_month = _sales_in_range(db, month_start, today)

    # Cost of sales = sum(cost_price * quantity) for active invoices
    cos_month = (
        db.query(func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity))
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(
            models.Invoice.invoice_date >= month_start,
            models.Invoice.invoice_date <= today,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .scalar() or 0
    )
    cos_all = (
        db.query(func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity))
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .scalar() or 0
    )

    active_customers = (
        db.query(func.count(models.Customer.id))
        .filter(models.Customer.is_active == True)
        .scalar() or 0
    )

    products_sold_today = (
        db.query(func.sum(models.InvoiceItem.quantity))
        .join(models.Invoice)
        .filter(
            models.Invoice.invoice_date == today,
            models.Invoice.status == models.InvoiceStatus.active,
        )
        .scalar() or 0
    )

    # Top 5 customers by sales (all time)
    top_customers = (
        db.query(
            models.Customer.id,
            models.Customer.customer_name,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(5)
        .all()
    )

    # Top 5 products
    top_products = (
        db.query(
            models.Product.id,
            models.Product.product_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(5)
        .all()
    )

    # Delivery vs pickup
    delivery_rows = (
        db.query(models.Invoice.delivery_type, func.sum(models.Invoice.total_amount).label("total"))
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Invoice.delivery_type)
        .all()
    )
    delivery_vs_pickup = {r.delivery_type.value: float(r.total or 0) for r in delivery_rows}

    # Sales by payment term
    pt_rows = (
        db.query(models.Invoice.payment_term, func.sum(models.Invoice.total_amount).label("total"))
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Invoice.payment_term)
        .all()
    )
    sales_by_pt = {r.payment_term: float(r.total or 0) for r in pt_rows}

    # Recent
    recent_invoices = (
        db.query(models.Invoice)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .order_by(models.Invoice.created_at.desc())
        .limit(5)
        .all()
    )
    recent_quotations = (
        db.query(models.Quotation)
        .order_by(models.Quotation.created_at.desc())
        .limit(5)
        .all()
    )

    return schemas.DashboardOverview(
        quotations_today=quotations_today,
        invoices_today=invoices_today,
        sales_today=sales_today,
        sales_this_week=sales_week,
        sales_this_month=sales_month,
        active_customers=active_customers,
        products_sold_today=float(products_sold_today),
        cost_of_sales_this_month=float(cos_month),
        cost_of_sales_all_time=float(cos_all),
        top_customers=[
            {"customer_id": r.id, "customer_name": r.customer_name, "total_sales": float(r.total)}
            for r in top_customers
        ],
        top_products=[
            {"product_id": r.id, "product_name": r.product_name, "total_sales": float(r.total)}
            for r in top_products
        ],
        delivery_vs_pickup=delivery_vs_pickup,
        sales_by_payment_term=sales_by_pt,
        recent_invoices=[
            {
                "id": inv.id, "invoice_number": inv.invoice_number,
                "customer_name": inv.customer.customer_name if inv.customer else "",
                "total_amount": float(inv.total_amount),
                "invoice_date": str(inv.invoice_date),
            }
            for inv in recent_invoices
        ],
        recent_quotations=[
            {
                "id": q.id, "quotation_number": q.quotation_number,
                "customer_name": q.customer.customer_name if q.customer else "",
                "total_amount": float(q.total_amount),
                "status": q.status.value,
                "quotation_date": str(q.quotation_date),
            }
            for q in recent_quotations
        ],
    )
