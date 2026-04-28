from typing import Optional, List
from datetime import date, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case, String

from database import get_db
from dependencies import get_current_user
import models
import schemas

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _enum_or_str_value(v):
    return v.value if hasattr(v, "value") else str(v)


def _inv_filters(invoice_query, date_from, date_to, delivery_type=None, payment_term=None,
                 staff_id=None, customer_id=None):
    # Cast enum/text status to string for robust cross-environment matching.
    invoice_status_text = func.lower(models.Invoice.status.cast(String))
    invoice_query = invoice_query.filter(invoice_status_text != "cancelled")
    if date_from:
        invoice_query = invoice_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        invoice_query = invoice_query.filter(models.Invoice.invoice_date <= date_to)
    if delivery_type:
        invoice_query = invoice_query.filter(models.Invoice.delivery_type == delivery_type)
    if payment_term:
        invoice_query = invoice_query.filter(models.Invoice.payment_term == payment_term)
    if staff_id:
        invoice_query = invoice_query.filter(models.Invoice.created_by == staff_id)
    if customer_id:
        invoice_query = invoice_query.filter(models.Invoice.customer_id == customer_id)
    return invoice_query


def _invoice_ids_for_market(db: Session, market_id: Optional[int]):
    if not market_id:
        return None
    return (
        db.query(models.InvoiceItem.invoice_id)
        .join(models.Product, models.Product.id == models.InvoiceItem.product_id)
        .filter(models.Product.category_id == market_id)
        .distinct()
        .subquery()
    )


def _invoice_ids_for_product(db: Session, product_id: Optional[int]):
    if not product_id:
        return None
    return (
        db.query(models.InvoiceItem.invoice_id)
        .filter(models.InvoiceItem.product_id == product_id)
        .distinct()
        .subquery()
    )


@router.get("/sales", response_model=schemas.SalesAnalytics)
def sales_analytics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    staff_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    selected_market_id = market_id or category_id
    market_invoice_ids_subquery = _invoice_ids_for_market(db, selected_market_id)
    product_invoice_ids_subquery = _invoice_ids_for_product(db, product_id)

    filtered_invoice_query = _inv_filters(
        db.query(models.Invoice.id.label("invoice_id")), date_from, date_to,
        delivery_type, payment_term, staff_id, customer_id,
    )
    if market_invoice_ids_subquery is not None:
        filtered_invoice_query = filtered_invoice_query.filter(models.Invoice.id.in_(market_invoice_ids_subquery))
    if product_invoice_ids_subquery is not None:
        filtered_invoice_query = filtered_invoice_query.filter(models.Invoice.id.in_(product_invoice_ids_subquery))
    filtered_invoice_ids = [row.invoice_id for row in filtered_invoice_query.distinct().all()]
    if not filtered_invoice_ids:
        return schemas.SalesAnalytics(
            total_sales_value=0,
            total_invoices=0,
            total_quotations=0,
            quotation_conversion_rate=0,
            average_invoice_value=0,
            top_customers=[],
            top_products=[],
            top_markets=[],
            top_categories=[],
            sales_by_delivery_type={},
            sales_by_payment_term={},
            sales_by_staff=[],
            daily_trend=[],
            monthly_trend=[],
        )

    total_invoice_count = (
        db.query(func.count(func.distinct(models.Invoice.id)))
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .scalar() or 0
    )
    total_sales_value = (
        db.query(func.sum(models.InvoiceItem.line_total))
        .filter(models.InvoiceItem.invoice_id.in_(filtered_invoice_ids))
        .scalar() or 0
    )

    quotation_count_query = db.query(func.count(models.Quotation.id))
    if date_from:
        quotation_count_query = quotation_count_query.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        quotation_count_query = quotation_count_query.filter(models.Quotation.quotation_date <= date_to)
    total_quotation_count = quotation_count_query.scalar() or 0

    conversion_rate = (total_invoice_count / total_quotation_count * 100) if total_quotation_count else 0
    average_invoice_value = (float(total_sales_value) / total_invoice_count) if total_invoice_count else 0

    top_customers_rows = (
        db.query(
            models.Customer.id,
            models.Customer.customer_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10)
        .all()
    )

    top_products_query = (
        db.query(
            models.Product.id,
            models.Product.product_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.sum(models.InvoiceItem.quantity).label("qty"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
    )
    if selected_market_id:
        top_products_query = top_products_query.filter(models.Product.category_id == selected_market_id)
    if product_id:
        top_products_query = top_products_query.filter(models.Product.id == product_id)
    top_products_rows = (
        top_products_query
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10)
        .all()
    )

    top_markets_query = (
        db.query(
            models.ProductCategory.id,
            models.ProductCategory.name,
            func.sum(models.InvoiceItem.line_total).label("total"),
        )
        .join(models.Product, models.Product.category_id == models.ProductCategory.id)
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
    )
    if selected_market_id:
        top_markets_query = top_markets_query.filter(models.Product.category_id == selected_market_id)
    top_markets_rows = (
        top_markets_query
        .group_by(models.ProductCategory.id, models.ProductCategory.name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10)
        .all()
    )

    delivery_split_rows = (
        db.query(
            models.Invoice.delivery_type,
            func.sum(models.InvoiceItem.line_total).label("t"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .group_by(models.Invoice.delivery_type)
        .all()
    )

    payment_term_split_rows = (
        db.query(
            models.Invoice.payment_term,
            func.sum(models.InvoiceItem.line_total).label("t"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .group_by(models.Invoice.payment_term)
        .all()
    )

    staff_sales_rows = (
        db.query(
            models.User.id,
            models.User.full_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.count(func.distinct(models.Invoice.id)).label("count"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .group_by(models.User.id, models.User.full_name)
        .all()
    )

    trend_start_date = date_from or (date.today() - timedelta(days=30))
    trend_end_date = date_to or date.today()

    daily_trend_rows = (
        db.query(
            models.Invoice.invoice_date,
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.count(func.distinct(models.Invoice.id)).label("count"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(
            models.Invoice.id.in_(filtered_invoice_ids),
            models.Invoice.invoice_date >= trend_start_date,
            models.Invoice.invoice_date <= trend_end_date,
        )
        .group_by(models.Invoice.invoice_date)
        .order_by(models.Invoice.invoice_date)
        .all()
    )

    monthly_trend_rows = (
        db.query(
            extract("year", models.Invoice.invoice_date).label("year"),
            extract("month", models.Invoice.invoice_date).label("month"),
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.count(func.distinct(models.Invoice.id)).label("count"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .filter(models.Invoice.id.in_(filtered_invoice_ids))
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    return schemas.SalesAnalytics(
        total_sales_value=float(total_sales_value or 0),
        total_invoices=total_invoice_count,
        total_quotations=total_quotation_count,
        quotation_conversion_rate=round(conversion_rate, 2),
        average_invoice_value=round(average_invoice_value, 2),
        top_customers=[
            {"customer_id": customer_row.id, "customer_name": customer_row.customer_name, "total": float(customer_row.total or 0)}
            for customer_row in top_customers_rows
        ],
        top_products=[
            {"product_id": product_row.id, "product_name": product_row.product_name,
             "total": float(product_row.total or 0), "qty": float(product_row.qty or 0)}
            for product_row in top_products_rows
        ],
        top_markets=[
            {
                "category_id": market_row.id,
                "category_name": market_row.name,
                "market_id": market_row.id,
                "market_name": market_row.name,
                "total": float(market_row.total or 0),
            }
            for market_row in top_markets_rows
        ],
        top_categories=[
            {
                "category_id": market_row.id,
                "category_name": market_row.name,
                "market_id": market_row.id,
                "market_name": market_row.name,
                "total": float(market_row.total or 0),
            }
            for market_row in top_markets_rows
        ],
        sales_by_delivery_type={
            (_enum_or_str_value(delivery_row.delivery_type) if delivery_row.delivery_type is not None else "unknown"): float(delivery_row.t or 0)
            for delivery_row in delivery_split_rows
        },
        sales_by_payment_term={
            (str(payment_term_row.payment_term) if payment_term_row.payment_term is not None else "unknown"): float(payment_term_row.t or 0)
            for payment_term_row in payment_term_split_rows
        },
        sales_by_staff=[
            {"user_id": staff_row.id, "full_name": staff_row.full_name,
             "total_sales": float(staff_row.total or 0), "invoice_count": int(staff_row.count or 0)}
            for staff_row in staff_sales_rows
        ],
        daily_trend=[
            {"date": str(daily_row.invoice_date), "total": float(daily_row.total or 0), "count": int(daily_row.count or 0)}
            for daily_row in daily_trend_rows
        ],
        monthly_trend=[
            {"year": int(monthly_row.year), "month": int(monthly_row.month),
             "total": float(monthly_row.total or 0), "count": int(monthly_row.count or 0)}
            for monthly_row in monthly_trend_rows
        ],
    )


@router.get("/customer-behavior", response_model=List[schemas.CustomerBehaviorOut])
def customer_behavior(
    customer_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    inactive_days: int = 30,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    selected_market = market_id or category_id
    market_invoice_ids = _invoice_ids_for_market(db, selected_market)
    cutoff          = date.today() - timedelta(days=inactive_days)
    last_month_end  = date.today().replace(day=1) - timedelta(days=1)
    last_month_start= last_month_end.replace(day=1)
    this_month_start= date.today().replace(day=1)

    cust_q = db.query(models.Customer).filter(models.Customer.is_active == True)
    if customer_id:
        cust_q = cust_q.filter(models.Customer.id == customer_id)
    customers = cust_q.limit(limit).all()
    if not customers:
        return []

    customer_ids = [customer.id for customer in customers]

    # ── Batch: all active invoices for these customers (1 query) ─────────────
    all_invoices = (
        db.query(models.Invoice)
        .filter(
            models.Invoice.customer_id.in_(customer_ids),
            models.Invoice.status != models.InvoiceStatus.cancelled,
        )
    )
    if market_invoice_ids is not None:
        all_invoices = all_invoices.filter(models.Invoice.id.in_(market_invoice_ids))
    all_invoices = all_invoices.all()
    inv_by_cust: dict = defaultdict(list)
    for inv in all_invoices:
        inv_by_cust[inv.customer_id].append(inv)

    # ── Batch: top products per customer (1 query, group in Python) ───────────
    prod_rows = (
        db.query(
            models.Invoice.customer_id,
            models.Product.id.label("product_id"),
            models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(models.InvoiceItem.line_total).label("value"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .join(models.Product, models.Product.id == models.InvoiceItem.product_id)
        .filter(
            models.Invoice.customer_id.in_(customer_ids),
            models.Invoice.status != models.InvoiceStatus.cancelled,
        )
    )
    if selected_market:
        prod_rows = prod_rows.filter(models.Product.category_id == selected_market)
    prod_rows = prod_rows.group_by(
        models.Invoice.customer_id,
        models.Product.id,
        models.Product.product_name,
    ).all()
    top_prod_by_cust: dict = defaultdict(list)
    for product_row in prod_rows:
        top_prod_by_cust[product_row.customer_id].append({
            "product_id": product_row.product_id, "product_name": product_row.product_name,
            "qty": float(product_row.qty), "value": float(product_row.value),
        })
    for customer_id in top_prod_by_cust:
        top_prod_by_cust[customer_id].sort(key=lambda x: x["value"], reverse=True)
        top_prod_by_cust[customer_id] = top_prod_by_cust[customer_id][:10]

    # ── Build result list in Python ───────────────────────────────────────────
    results = []
    for customer in customers:
        invoices = inv_by_cust[customer.id]
        if not invoices:
            continue

        total_value = sum(float(inv.total_amount) for inv in invoices)
        dates       = sorted(inv.invoice_date for inv in invoices)
        last_date   = dates[-1]
        is_inactive = last_date < cutoff

        freq = None
        if len(dates) > 1:
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            freq = sum(gaps) / len(gaps)

        this_month_val = sum(
            float(inv.total_amount) for inv in invoices
            if inv.invoice_date >= this_month_start
        )
        last_month_val = sum(
            float(inv.total_amount) for inv in invoices
            if last_month_start <= inv.invoice_date <= last_month_end
        )
        mom_change = None
        if last_month_val:
            mom_change = round(
                (this_month_val - last_month_val) / last_month_val * 100, 2
            )

        results.append(schemas.CustomerBehaviorOut(
            customer_id=customer.id,
            customer_name=customer.customer_name,
            top_products=top_prod_by_cust[customer.id],
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
    market_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    product_sales_query = (
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
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        product_sales_query = product_sales_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        product_sales_query = product_sales_query.filter(models.Invoice.invoice_date <= date_to)
    selected_market = market_id or category_id
    if selected_market:
        product_sales_query = product_sales_query.filter(models.Product.category_id == selected_market)
    if delivery_type:
        product_sales_query = product_sales_query.filter(models.Invoice.delivery_type == delivery_type)
    if payment_term:
        product_sales_query = product_sales_query.filter(models.Invoice.payment_term == payment_term)

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
            "total_revenue": float(product_row.total_revenue),
            "unique_customers": product_row.unique_customers,
            "total_invoices": product_row.total_invoices,
        }
        for product_row in rows
    ]


@router.get("/staff-performance", response_model=List[schemas.StaffPerformanceOut])
def staff_performance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    selected_market = market_id or category_id
    market_invoice_ids = _invoice_ids_for_market(db, selected_market)
    users = db.query(models.User).filter(models.User.is_active == True)
    if user_id:
        users = users.filter(models.User.id == user_id)
    users = users.all()

    results = []
    for u in users:
        q_filter = [models.Quotation.created_by == u.id]
        i_filter = [models.Invoice.created_by == u.id,
                    models.Invoice.status != models.InvoiceStatus.cancelled]
        if date_from:
            q_filter.append(models.Quotation.quotation_date >= date_from)
            i_filter.append(models.Invoice.invoice_date >= date_from)
        if date_to:
            q_filter.append(models.Quotation.quotation_date <= date_to)
            i_filter.append(models.Invoice.invoice_date <= date_to)

        quot_count = (
            db.query(func.count(models.Quotation.id)).filter(*q_filter).scalar() or 0
        )
        inv_data_q = (
            db.query(
                func.count(models.Invoice.id).label("cnt"),
                func.sum(models.Invoice.total_amount).label("total"),
            )
            .filter(*i_filter)
        )
        if market_invoice_ids is not None:
            inv_data_q = inv_data_q.filter(models.Invoice.id.in_(market_invoice_ids))
        inv_data = inv_data_q.first()
        inv_count  = inv_data.cnt or 0
        inv_total  = float(inv_data.total or 0)
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


@router.get("/comprehensive", response_model=schemas.ComprehensiveStats)
def comprehensive_stats(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    selected_market = market_id or category_id
    market_invoice_ids = _invoice_ids_for_market(db, selected_market)
    # ── Quotation stats ────────────────────────────────────────────────────────
    quotation_base_query = db.query(models.Quotation)
    if date_from:
        quotation_base_query = quotation_base_query.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        quotation_base_query = quotation_base_query.filter(models.Quotation.quotation_date <= date_to)

    quot_status_rows = (
        quotation_base_query.with_entities(
            models.Quotation.status,
            func.count(models.Quotation.id).label("cnt"),
            func.sum(models.Quotation.total_amount).label("total_amount"),
        )
        .group_by(models.Quotation.status)
        .all()
    )
    quotation_stats_by_status: dict = {}
    for quotation_status_row in quot_status_rows:
        quotation_stats_by_status[quotation_status_row.status.value] = {"cnt": quotation_status_row.cnt, "total_amount": float(quotation_status_row.total_amount or 0)}

    q_total     = sum(status_stats["cnt"] for status_stats in quotation_stats_by_status.values())
    q_draft     = quotation_stats_by_status.get("draft", {}).get("cnt", 0)
    q_pending   = quotation_stats_by_status.get("pending_approval", {}).get("cnt", 0)
    q_approved  = quotation_stats_by_status.get("approved", {}).get("cnt", 0)
    q_rejected  = quotation_stats_by_status.get("rejected", {}).get("cnt", 0)
    q_converted = quotation_stats_by_status.get("converted", {}).get("cnt", 0)
    q_total_amount = sum(status_stats["total_amount"] for status_stats in quotation_stats_by_status.values())
    submitted   = q_pending + q_approved + q_rejected + q_converted
    approval_r  = round((q_approved + q_converted) / submitted * 100, 2) if submitted else 0
    rejection_r = round(q_rejected / submitted * 100, 2) if submitted else 0
    conv_r      = round(
        q_converted / (q_approved + q_converted) * 100, 2
    ) if (q_approved + q_converted) else 0

    quot_stats = schemas.QuotationStats(
        total=q_total, draft=q_draft, pending_approval=q_pending,
        approved=q_approved, rejected=q_rejected, converted=q_converted,
        approval_rate=approval_r, rejection_rate=rejection_r,
        conversion_rate=conv_r, total_value=q_total_amount,
    )

    # ── Invoice stats ──────────────────────────────────────────────────────────
    invoice_base_query = db.query(models.Invoice)
    if date_from:
        invoice_base_query = invoice_base_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        invoice_base_query = invoice_base_query.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        invoice_base_query = invoice_base_query.filter(models.Invoice.id.in_(market_invoice_ids))

    inv_status_rows = (
        invoice_base_query.with_entities(
            models.Invoice.status,
            func.count(models.Invoice.id).label("cnt"),
            func.sum(models.Invoice.total_amount).label("billed"),
            func.sum(models.Invoice.amount_paid).label("collected"),
        )
        .group_by(models.Invoice.status)
        .all()
    )
    invoice_stats_by_status: dict = {}
    for invoice_status_row in inv_status_rows:
        invoice_stats_by_status[invoice_status_row.status.value] = {
            "cnt": invoice_status_row.cnt,
            "billed": float(invoice_status_row.billed or 0),
            "collected": float(invoice_status_row.collected or 0),
        }

    i_total     = sum(status_stats["cnt"] for status_stats in invoice_stats_by_status.values())
    i_active    = invoice_stats_by_status.get("active", {}).get("cnt", 0)
    i_partial   = invoice_stats_by_status.get("partially_paid", {}).get("cnt", 0)
    i_paid      = invoice_stats_by_status.get("paid", {}).get("cnt", 0) + invoice_stats_by_status.get("completed", {}).get("cnt", 0)
    i_cancelled = invoice_stats_by_status.get("cancelled", {}).get("cnt", 0)
    non_cancelled= i_total - i_cancelled
    paid_rate_v = round(i_paid / non_cancelled * 100, 2) if non_cancelled else 0
    cancel_rate_v= round(i_cancelled / i_total * 100, 2) if i_total else 0
    total_billed = sum(status_stats["billed"] for status_name, status_stats in invoice_stats_by_status.items() if status_name != "cancelled")
    total_coll   = sum(status_stats["collected"] for status_name, status_stats in invoice_stats_by_status.items() if status_name != "cancelled")
    total_out    = total_billed - total_coll
    coll_rate    = round(total_coll / total_billed * 100, 2) if total_billed else 0

    inv_stats = schemas.InvoiceStats(
        total=i_total, active=i_active, partially_paid=i_partial,
        paid=i_paid, cancelled=i_cancelled,
        paid_rate=paid_rate_v, cancel_rate=cancel_rate_v,
        total_billed=total_billed, total_collected=total_coll,
        total_outstanding=total_out, collection_rate=coll_rate,
    )

    # ── Payment stats ──────────────────────────────────────────────────────────
    pay_rows = (
        db.query(
            models.Payment.status,
            func.count(models.Payment.id).label("cnt"),
            func.sum(models.Payment.amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.id == models.Payment.invoice_id)
    )
    if market_invoice_ids is not None:
        pay_rows = pay_rows.filter(models.Invoice.id.in_(market_invoice_ids))
    pay_rows = pay_rows.group_by(models.Payment.status).all()
    payment_stats_by_status: dict = {
        payment_row.status.value: {"cnt": payment_row.cnt, "total": float(payment_row.total or 0)}
        for payment_row in pay_rows
    }
    pay_stats = schemas.PaymentStats(
        total=sum(status_stats["cnt"] for status_stats in payment_stats_by_status.values()),
        pending=payment_stats_by_status.get("pending", {}).get("cnt", 0),
        confirmed=payment_stats_by_status.get("confirmed", {}).get("cnt", 0),
        voided=payment_stats_by_status.get("voided", {}).get("cnt", 0),
        failed=payment_stats_by_status.get("failed", {}).get("cnt", 0),
        total_amount=sum(status_stats["total"] for status_stats in payment_stats_by_status.values()),
        confirmed_amount=payment_stats_by_status.get("confirmed", {}).get("total", 0),
        pending_amount=payment_stats_by_status.get("pending", {}).get("total", 0),
    )

    # ── Per-sales-person stats (2 batch queries instead of N*2) ───────────────
    all_users = db.query(models.User).filter(models.User.is_active == True).all()
    user_map  = {u.id: u for u in all_users}

    uq_base = db.query(
        models.Quotation.created_by,
        models.Quotation.status,
        func.count(models.Quotation.id).label("cnt"),
    )
    if date_from:
        uq_base = uq_base.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        uq_base = uq_base.filter(models.Quotation.quotation_date <= date_to)
    uq_all = uq_base.group_by(
        models.Quotation.created_by, models.Quotation.status
    ).all()

    ui_base = db.query(
        models.Invoice.created_by,
        models.Invoice.status,
        func.count(models.Invoice.id).label("cnt"),
        func.sum(models.Invoice.total_amount).label("billed"),
        func.sum(models.Invoice.amount_paid).label("collected"),
    )
    if date_from:
        ui_base = ui_base.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        ui_base = ui_base.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        ui_base = ui_base.filter(models.Invoice.id.in_(market_invoice_ids))
    ui_all = ui_base.group_by(
        models.Invoice.created_by, models.Invoice.status
    ).all()

    quotation_counts_by_user: dict = defaultdict(dict)
    for quotation_summary_row in uq_all:
        quotation_counts_by_user[quotation_summary_row.created_by][quotation_summary_row.status.value] = quotation_summary_row.cnt

    invoice_amounts_by_user: dict = defaultdict(dict)
    for invoice_summary_row in ui_all:
        invoice_amounts_by_user[invoice_summary_row.created_by][invoice_summary_row.status.value] = {
            "cnt": invoice_summary_row.cnt,
            "billed": float(invoice_summary_row.billed or 0),
            "collected": float(invoice_summary_row.collected or 0),
        }

    by_sales: list = []
    for u in all_users:
        uqmap = quotation_counts_by_user[u.id]
        uimap = invoice_amounts_by_user[u.id]
        uq_total   = sum(uqmap.values())
        uq_draft   = uqmap.get("draft", 0)
        uq_pending = uqmap.get("pending_approval", 0)
        uq_appr    = uqmap.get("approved", 0)
        uq_rej     = uqmap.get("rejected", 0)
        uq_conv    = uqmap.get("converted", 0)
        uq_sub     = uq_pending + uq_appr + uq_rej + uq_conv
        uq_appr_r  = round((uq_appr + uq_conv) / uq_sub * 100, 2) if uq_sub else 0
        uq_conv_r  = round(
            uq_conv / (uq_appr + uq_conv) * 100, 2
        ) if (uq_appr + uq_conv) else 0

        ui_total   = sum(v["cnt"] for v in uimap.values())
        ui_paid    = uimap.get("paid", {}).get("cnt", 0) + uimap.get("completed", {}).get("cnt", 0)
        ui_partial = uimap.get("partially_paid", {}).get("cnt", 0)
        ui_active  = uimap.get("active", {}).get("cnt", 0)
        ui_cancel  = uimap.get("cancelled", {}).get("cnt", 0)
        ui_billed  = sum(v["billed"]    for k, v in uimap.items() if k != "cancelled")
        ui_coll    = sum(v["collected"] for k, v in uimap.items() if k != "cancelled")
        ui_out     = ui_billed - ui_coll
        ui_coll_r  = round(ui_coll / ui_billed * 100, 2) if ui_billed else 0
        ui_avg     = ui_billed / (ui_total - ui_cancel) if (ui_total - ui_cancel) else 0

        if uq_total == 0 and ui_total == 0:
            continue

        by_sales.append(schemas.SalesPersonStats(
            user_id=u.id, full_name=u.full_name, username=u.username,
            role=u.role.value,
            quotations_total=uq_total, quotations_draft=uq_draft,
            quotations_pending=uq_pending, quotations_approved=uq_appr,
            quotations_rejected=uq_rej, quotations_converted=uq_conv,
            quotation_approval_rate=uq_appr_r, quotation_conversion_rate=uq_conv_r,
            invoices_total=ui_total, invoices_paid=ui_paid,
            invoices_partially_paid=ui_partial, invoices_active=ui_active,
            invoices_cancelled=ui_cancel,
            total_billed=ui_billed, total_collected=ui_coll,
            total_outstanding=ui_out, collection_rate=ui_coll_r,
            avg_invoice_value=round(ui_avg, 2),
        ))
    by_sales.sort(key=lambda x: x.total_billed, reverse=True)

    # ── Per-manager stats ──────────────────────────────────────────────────────
    manager_rows = (
        db.query(
            models.User.id, models.User.full_name, models.User.username,
            models.Quotation.status,
            func.count(models.Quotation.id).label("cnt"),
            func.sum(models.Quotation.total_amount).label("total_amount"),
        )
        .join(models.Quotation, models.Quotation.approved_by == models.User.id)
        .filter(models.Quotation.status.in_([
            models.QuotationStatus.approved,
            models.QuotationStatus.rejected,
            models.QuotationStatus.converted,
        ]))
        .group_by(
            models.User.id, models.User.full_name,
            models.User.username, models.Quotation.status,
        )
        .all()
    )

    manager_stats_map: dict = {}
    for manager_status_row in manager_rows:
        if manager_status_row.id not in manager_stats_map:
            manager_stats_map[manager_status_row.id] = {
                "full_name": manager_status_row.full_name, "username": manager_status_row.username, "statuses": {}
            }
        manager_stats_map[manager_status_row.id]["statuses"][manager_status_row.status.value] = {
            "cnt": manager_status_row.cnt, "total_amount": float(manager_status_row.total_amount or 0)
        }

    # Top sales people per manager (batch: one query for all managers)
    top_sales_rows = (
        db.query(
            models.Quotation.approved_by,
            models.User.full_name,
            func.count(models.Quotation.id).label("cnt"),
            func.sum(models.Quotation.total_amount).label("total_amount"),
        )
        .join(models.User, models.User.id == models.Quotation.created_by)
        .filter(
            models.Quotation.approved_by.in_(list(manager_stats_map.keys())),
            models.Quotation.status.in_([
                models.QuotationStatus.approved,
                models.QuotationStatus.converted,
            ]),
        )
        .group_by(models.Quotation.approved_by, models.User.id, models.User.full_name)
        .order_by(func.sum(models.Quotation.total_amount).desc())
        .all()
    )
    top_sales_by_mgr: dict = defaultdict(list)
    for top_sales_row in top_sales_rows:
        top_sales_by_mgr[top_sales_row.approved_by].append(
            {"name": top_sales_row.full_name, "count": top_sales_row.cnt, "value": float(top_sales_row.total_amount)}
        )

    by_manager: list = []
    for uid, m in manager_stats_map.items():
        s = m["statuses"]
        approved_cnt = s.get("approved", {}).get("cnt", 0) + s.get("converted", {}).get("cnt", 0)
        rejected_cnt = s.get("rejected", {}).get("cnt", 0)
        reviewed     = approved_cnt + rejected_cnt
        appr_r       = round(approved_cnt / reviewed * 100, 2) if reviewed else 0
        rej_r        = round(rejected_cnt / reviewed * 100, 2) if reviewed else 0
        rev_approved = sum(v["total_amount"] for k, v in s.items() if k in ("approved", "converted"))

        by_manager.append(schemas.ManagerStats(
            user_id=uid, full_name=m["full_name"], username=m["username"],
            reviewed_total=reviewed, approved_count=approved_cnt,
            rejected_count=rejected_cnt,
            approval_rate=appr_r, rejection_rate=rej_r,
            revenue_approved=rev_approved,
            top_sales=top_sales_by_mgr[uid][:5],
        ))
    by_manager.sort(key=lambda x: x.revenue_approved, reverse=True)

    # ── Revenue by role ────────────────────────────────────────────────────────
    revenue_by_role_query = (
        db.query(
            models.User.role,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        revenue_by_role_query = revenue_by_role_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        revenue_by_role_query = revenue_by_role_query.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        revenue_by_role_query = revenue_by_role_query.filter(models.Invoice.id.in_(market_invoice_ids))
    role_rows = revenue_by_role_query.group_by(models.User.role).all()
    revenue_by_role = {role_row.role.value: float(role_row.total or 0) for role_row in role_rows}

    # ── Top customers + products (all-time or filtered) ────────────────────────
    top_customers_query = (
        db.query(
            models.Customer.id, models.Customer.customer_name,
            func.count(func.distinct(models.Invoice.id)).label("orders"),
            func.sum(models.Invoice.total_amount).label("billed"),
            func.sum(models.Invoice.amount_paid).label("collected"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        top_customers_query = top_customers_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        top_customers_query = top_customers_query.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        top_customers_query = top_customers_query.filter(models.Invoice.id.in_(market_invoice_ids))
    top_cust_rows = (
        top_customers_query.group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(20).all()
    )

    top_products_query = (
        db.query(
            models.Product.id, models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
            func.count(func.distinct(models.Invoice.customer_id)).label("customers"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        top_products_query = top_products_query.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        top_products_query = top_products_query.filter(models.Invoice.invoice_date <= date_to)
    if selected_market:
        top_products_query = top_products_query.filter(models.Product.category_id == selected_market)
    top_prod_rows = (
        top_products_query.group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(20).all()
    )

    return schemas.ComprehensiveStats(
        quotations=quot_stats,
        invoices=inv_stats,
        payments=pay_stats,
        by_sales_person=by_sales,
        by_manager=by_manager,
        revenue_by_role=revenue_by_role,
        top_customers_revenue=[
            {
                "customer_id": customer_row.id, "customer_name": customer_row.customer_name,
                "orders": customer_row.orders, "billed": float(customer_row.billed),
                "collected": float(customer_row.collected),
                "outstanding": float(customer_row.billed) - float(customer_row.collected),
                "collection_rate": round(
                    float(customer_row.collected) / float(customer_row.billed) * 100, 1
                ) if customer_row.billed else 0,
            }
            for customer_row in top_cust_rows
        ],
        top_products_revenue=[
            {
                "product_id": product_row.id, "product_name": product_row.product_name,
                "qty": float(product_row.qty), "revenue": float(product_row.revenue),
                "customers": product_row.customers,
            }
            for product_row in top_prod_rows
        ],
    )
