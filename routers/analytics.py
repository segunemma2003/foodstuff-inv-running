from typing import Optional, List
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case

from database import get_db
from dependencies import get_current_user
import models
import schemas

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _active_invoices(db: Session, date_from: Optional[date], date_to: Optional[date]):
    q = db.query(models.Invoice).filter(models.Invoice.status == models.InvoiceStatus.active)
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    return q


@router.get("/sales", response_model=schemas.SalesAnalytics)
def sales_analytics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    category_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    staff_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    inv_q = db.query(models.Invoice).filter(models.Invoice.status == models.InvoiceStatus.active)
    if date_from:
        inv_q = inv_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        inv_q = inv_q.filter(models.Invoice.invoice_date <= date_to)
    if customer_id:
        inv_q = inv_q.filter(models.Invoice.customer_id == customer_id)
    if delivery_type:
        inv_q = inv_q.filter(models.Invoice.delivery_type == delivery_type)
    if payment_term:
        inv_q = inv_q.filter(models.Invoice.payment_term == payment_term)
    if staff_id:
        inv_q = inv_q.filter(models.Invoice.created_by == staff_id)

    invoices = inv_q.all()
    total_value = sum(float(i.total_amount) for i in invoices)
    total_inv = len(invoices)

    # Quotation count for conversion rate
    quot_q = db.query(func.count(models.Quotation.id))
    if date_from:
        quot_q = quot_q.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        quot_q = quot_q.filter(models.Quotation.quotation_date <= date_to)
    total_quot = quot_q.scalar() or 0
    conversion_rate = (total_inv / total_quot * 100) if total_quot else 0

    avg_inv = total_value / total_inv if total_inv else 0

    # Top customers
    top_cust = (
        db.query(
            models.Customer.id, models.Customer.customer_name,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(10).all()
    )

    # Top products
    top_prod = (
        db.query(
            models.Product.id, models.Product.product_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.sum(models.InvoiceItem.quantity).label("qty"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10).all()
    )

    # Top categories
    top_cat = (
        db.query(
            models.ProductCategory.id, models.ProductCategory.name,
            func.sum(models.InvoiceItem.line_total).label("total"),
        )
        .join(models.Product, models.Product.category_id == models.ProductCategory.id)
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.ProductCategory.id, models.ProductCategory.name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10).all()
    )

    # Sales by delivery type
    dt_rows = (
        db.query(models.Invoice.delivery_type, func.sum(models.Invoice.total_amount).label("t"))
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Invoice.delivery_type).all()
    )

    # Sales by payment term
    pt_rows = (
        db.query(models.Invoice.payment_term, func.sum(models.Invoice.total_amount).label("t"))
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.Invoice.payment_term).all()
    )

    # Sales by staff
    staff_rows = (
        db.query(
            models.User.id, models.User.full_name,
            func.sum(models.Invoice.total_amount).label("total"),
            func.count(models.Invoice.id).label("count"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by(models.User.id, models.User.full_name)
        .all()
    )

    # Daily trend (last 30 days)
    daily = (
        db.query(
            models.Invoice.invoice_date,
            func.sum(models.Invoice.total_amount).label("total"),
            func.count(models.Invoice.id).label("count"),
        )
        .filter(
            models.Invoice.status == models.InvoiceStatus.active,
            models.Invoice.invoice_date >= date.today() - timedelta(days=30),
        )
        .group_by(models.Invoice.invoice_date)
        .order_by(models.Invoice.invoice_date)
        .all()
    )

    # Monthly trend
    monthly = (
        db.query(
            extract("year", models.Invoice.invoice_date).label("year"),
            extract("month", models.Invoice.invoice_date).label("month"),
            func.sum(models.Invoice.total_amount).label("total"),
            func.count(models.Invoice.id).label("count"),
        )
        .filter(models.Invoice.status == models.InvoiceStatus.active)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    return schemas.SalesAnalytics(
        total_sales_value=total_value,
        total_invoices=total_inv,
        total_quotations=total_quot,
        quotation_conversion_rate=round(conversion_rate, 2),
        average_invoice_value=round(avg_inv, 2),
        top_customers=[
            {"customer_id": r.id, "customer_name": r.customer_name, "total": float(r.total)}
            for r in top_cust
        ],
        top_products=[
            {"product_id": r.id, "product_name": r.product_name,
             "total": float(r.total), "qty": float(r.qty)}
            for r in top_prod
        ],
        top_categories=[
            {"category_id": r.id, "category_name": r.name, "total": float(r.total)}
            for r in top_cat
        ],
        sales_by_delivery_type={r.delivery_type.value: float(r.t or 0) for r in dt_rows},
        sales_by_payment_term={r.payment_term: float(r.t or 0) for r in pt_rows},
        sales_by_staff=[
            {"user_id": r.id, "full_name": r.full_name,
             "total_sales": float(r.total), "invoice_count": r.count}
            for r in staff_rows
        ],
        daily_trend=[
            {"date": str(r.invoice_date), "total": float(r.total), "count": r.count}
            for r in daily
        ],
        monthly_trend=[
            {"year": int(r.year), "month": int(r.month), "total": float(r.total), "count": r.count}
            for r in monthly
        ],
    )


@router.get("/customer-behavior", response_model=List[schemas.CustomerBehaviorOut])
def customer_behavior(
    customer_id: Optional[int] = None,
    inactive_days: int = 30,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    cutoff = date.today() - timedelta(days=inactive_days)
    last_month_start = date.today().replace(day=1) - timedelta(days=1)
    last_month_start = last_month_start.replace(day=1)
    this_month_start = date.today().replace(day=1)

    cust_q = db.query(models.Customer).filter(models.Customer.is_active == True)
    if customer_id:
        cust_q = cust_q.filter(models.Customer.id == customer_id)
    customers = cust_q.all()

    results = []
    for c in customers:
        invoices = (
            db.query(models.Invoice)
            .filter(
                models.Invoice.customer_id == c.id,
                models.Invoice.status == models.InvoiceStatus.active,
            )
            .order_by(models.Invoice.invoice_date)
            .all()
        )
        if not invoices:
            continue

        total_value = sum(float(inv.total_amount) for inv in invoices)
        dates = sorted(inv.invoice_date for inv in invoices)
        last_date = dates[-1]
        is_inactive = last_date < cutoff

        # Purchase frequency (avg days between orders)
        if len(dates) > 1:
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            freq = sum(gaps) / len(gaps)
        else:
            freq = None

        # Month-over-month
        this_month_val = sum(
            float(inv.total_amount)
            for inv in invoices
            if inv.invoice_date >= this_month_start
        )
        last_month_val = sum(
            float(inv.total_amount)
            for inv in invoices
            if last_month_start <= inv.invoice_date < this_month_start
        )
        mom_change = None
        if last_month_val:
            mom_change = round((this_month_val - last_month_val) / last_month_val * 100, 2)

        # Top products
        top_p = (
            db.query(
                models.Product.id,
                models.Product.product_name,
                func.sum(models.InvoiceItem.quantity).label("qty"),
                func.sum(models.InvoiceItem.line_total).label("value"),
            )
            .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
            .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
            .filter(
                models.Invoice.customer_id == c.id,
                models.Invoice.status == models.InvoiceStatus.active,
            )
            .group_by(models.Product.id, models.Product.product_name)
            .order_by(func.sum(models.InvoiceItem.line_total).desc())
            .limit(10)
            .all()
        )

        results.append(schemas.CustomerBehaviorOut(
            customer_id=c.id,
            customer_name=c.customer_name,
            top_products=[
                {"product_id": r.id, "product_name": r.product_name,
                 "qty": float(r.qty), "value": float(r.value)}
                for r in top_p
            ],
            purchase_frequency_days=freq,
            total_orders=len(invoices),
            total_value=total_value,
            last_order_date=last_date,
            is_inactive_30_days=is_inactive,
            month_over_month_change_pct=mom_change,
        ))

    return results


@router.get("/product-sales")
def product_sales_analytics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    category_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = (
        db.query(
            models.Product.id,
            models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("total_qty"),
            func.sum(models.InvoiceItem.line_total).label("total_revenue"),
            func.count(func.distinct(models.Invoice.customer_id)).label("unique_customers"),
            func.count(func.distinct(models.Invoice.id)).label("total_invoices"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status == models.InvoiceStatus.active)
    )
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    if category_id:
        q = q.filter(models.Product.category_id == category_id)
    if delivery_type:
        q = q.filter(models.Invoice.delivery_type == delivery_type)
    if payment_term:
        q = q.filter(models.Invoice.payment_term == payment_term)

    rows = (
        q.group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": r.id,
            "product_name": r.product_name,
            "total_qty": float(r.total_qty),
            "total_revenue": float(r.total_revenue),
            "unique_customers": r.unique_customers,
            "total_invoices": r.total_invoices,
        }
        for r in rows
    ]


@router.get("/staff-performance", response_model=List[schemas.StaffPerformanceOut])
def staff_performance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    users = db.query(models.User).filter(models.User.is_active == True)
    if user_id:
        users = users.filter(models.User.id == user_id)
    users = users.all()

    results = []
    for u in users:
        q_filter = [models.Quotation.created_by == u.id]
        i_filter = [models.Invoice.created_by == u.id, models.Invoice.status == models.InvoiceStatus.active]
        if date_from:
            q_filter.append(models.Quotation.quotation_date >= date_from)
            i_filter.append(models.Invoice.invoice_date >= date_from)
        if date_to:
            q_filter.append(models.Quotation.quotation_date <= date_to)
            i_filter.append(models.Invoice.invoice_date <= date_to)

        quot_count = db.query(func.count(models.Quotation.id)).filter(*q_filter).scalar() or 0
        inv_data = (
            db.query(
                func.count(models.Invoice.id).label("cnt"),
                func.sum(models.Invoice.total_amount).label("total"),
            )
            .filter(*i_filter)
            .first()
        )
        inv_count = inv_data.cnt or 0
        inv_total = float(inv_data.total or 0)
        conversion = (inv_count / quot_count * 100) if quot_count else 0

        results.append(schemas.StaffPerformanceOut(
            user_id=u.id,
            full_name=u.full_name,
            username=u.username,
            quotations_created=quot_count,
            invoices_created=inv_count,
            total_sales_value=inv_total,
            conversion_rate=round(conversion, 2),
        ))

    return sorted(results, key=lambda x: x.total_sales_value, reverse=True)
