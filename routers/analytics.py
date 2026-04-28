from typing import Optional, List
from datetime import date, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case

from database import get_db
from dependencies import get_current_user
import models
import schemas

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _inv_filters(q, date_from, date_to, delivery_type=None, payment_term=None,
                 staff_id=None, customer_id=None):
    q = q.filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    if delivery_type:
        q = q.filter(models.Invoice.delivery_type == delivery_type)
    if payment_term:
        q = q.filter(models.Invoice.payment_term == payment_term)
    if staff_id:
        q = q.filter(models.Invoice.created_by == staff_id)
    if customer_id:
        q = q.filter(models.Invoice.customer_id == customer_id)
    return q


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
    selected_market = market_id or category_id
    market_invoice_ids = _invoice_ids_for_market(db, selected_market)
    product_invoice_ids = _invoice_ids_for_product(db, product_id)

    # ── Core invoice query ────────────────────────────────────────────────────
    inv_q = _inv_filters(
        db.query(models.Invoice), date_from, date_to,
        delivery_type, payment_term, staff_id, customer_id,
    )
    if market_invoice_ids is not None:
        inv_q = inv_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        inv_q = inv_q.filter(models.Invoice.id.in_(product_invoice_ids))
    invoices = inv_q.all()
    total_value = sum(float(i.total_amount) for i in invoices)
    total_inv   = len(invoices)

    quot_q = db.query(func.count(models.Quotation.id))
    if date_from:
        quot_q = quot_q.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        quot_q = quot_q.filter(models.Quotation.quotation_date <= date_to)
    total_quot   = quot_q.scalar() or 0
    conversion_rate = (total_inv / total_quot * 100) if total_quot else 0
    avg_inv = total_value / total_inv if total_inv else 0

    # ── Top customers (with same filters) ─────────────────────────────────────
    tc_q = (
        db.query(
            models.Customer.id, models.Customer.customer_name,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
    )
    tc_q = _inv_filters(tc_q, date_from, date_to, delivery_type, payment_term, staff_id, customer_id)
    if market_invoice_ids is not None:
        tc_q = tc_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        tc_q = tc_q.filter(models.Invoice.id.in_(product_invoice_ids))
    top_cust = (
        tc_q.group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(10).all()
    )

    # ── Top products ──────────────────────────────────────────────────────────
    tp_q = (
        db.query(
            models.Product.id, models.Product.product_name,
            func.sum(models.InvoiceItem.line_total).label("total"),
            func.sum(models.InvoiceItem.quantity).label("qty"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
    )
    tp_q = _inv_filters(tp_q, date_from, date_to, delivery_type, payment_term, staff_id, customer_id)
    if selected_market:
        tp_q = tp_q.filter(models.Product.category_id == selected_market)
    if product_id:
        tp_q = tp_q.filter(models.Product.id == product_id)
    top_prod = (
        tp_q.group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10).all()
    )

    # ── Top categories ────────────────────────────────────────────────────────
    tcat_q = (
        db.query(
            models.ProductCategory.id, models.ProductCategory.name,
            func.sum(models.InvoiceItem.line_total).label("total"),
        )
        .join(models.Product, models.Product.category_id == models.ProductCategory.id)
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
    )
    tcat_q = _inv_filters(tcat_q, date_from, date_to, delivery_type, payment_term, staff_id, customer_id)
    if selected_market:
        tcat_q = tcat_q.filter(models.Product.category_id == selected_market)
    top_cat = (
        tcat_q.group_by(models.ProductCategory.id, models.ProductCategory.name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(10).all()
    )

    # ── Sales by delivery type ────────────────────────────────────────────────
    dt_q = db.query(
        models.Invoice.delivery_type,
        func.sum(models.Invoice.total_amount).label("t"),
    )
    dt_q = _inv_filters(dt_q, date_from, date_to, None, payment_term, staff_id, customer_id)
    if market_invoice_ids is not None:
        dt_q = dt_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        dt_q = dt_q.filter(models.Invoice.id.in_(product_invoice_ids))
    dt_rows = dt_q.group_by(models.Invoice.delivery_type).all()

    # ── Sales by payment term ─────────────────────────────────────────────────
    pt_q = db.query(
        models.Invoice.payment_term,
        func.sum(models.Invoice.total_amount).label("t"),
    )
    pt_q = _inv_filters(pt_q, date_from, date_to, delivery_type, None, staff_id, customer_id)
    if market_invoice_ids is not None:
        pt_q = pt_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        pt_q = pt_q.filter(models.Invoice.id.in_(product_invoice_ids))
    pt_rows = pt_q.group_by(models.Invoice.payment_term).all()

    # ── Sales by staff ────────────────────────────────────────────────────────
    st_q = (
        db.query(
            models.User.id, models.User.full_name,
            func.sum(models.Invoice.total_amount).label("total"),
            func.count(models.Invoice.id).label("count"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
    )
    st_q = _inv_filters(st_q, date_from, date_to, delivery_type, payment_term, None, customer_id)
    if market_invoice_ids is not None:
        st_q = st_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        st_q = st_q.filter(models.Invoice.id.in_(product_invoice_ids))
    staff_rows = st_q.group_by(models.User.id, models.User.full_name).all()

    # ── Daily trend (last 30 days or within date range) ───────────────────────
    daily_from = date_from or (date.today() - timedelta(days=30))
    daily_to   = date_to   or date.today()
    daily_q = (
        db.query(
            models.Invoice.invoice_date,
            func.sum(models.Invoice.total_amount).label("total"),
            func.count(models.Invoice.id).label("count"),
        )
    )
    daily_q = _inv_filters(
        daily_q, daily_from, daily_to,
        delivery_type, payment_term, staff_id, customer_id,
    )
    if market_invoice_ids is not None:
        daily_q = daily_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        daily_q = daily_q.filter(models.Invoice.id.in_(product_invoice_ids))
    daily = (
        daily_q
        .group_by(models.Invoice.invoice_date)
        .order_by(models.Invoice.invoice_date)
        .all()
    )

    # ── Monthly trend ─────────────────────────────────────────────────────────
    mon_q = db.query(
        extract("year",  models.Invoice.invoice_date).label("year"),
        extract("month", models.Invoice.invoice_date).label("month"),
        func.sum(models.Invoice.total_amount).label("total"),
        func.count(models.Invoice.id).label("count"),
    )
    mon_q = _inv_filters(
        mon_q, date_from, date_to,
        delivery_type, payment_term, staff_id, customer_id,
    )
    if market_invoice_ids is not None:
        mon_q = mon_q.filter(models.Invoice.id.in_(market_invoice_ids))
    if product_invoice_ids is not None:
        mon_q = mon_q.filter(models.Invoice.id.in_(product_invoice_ids))
    monthly = mon_q.group_by("year", "month").order_by("year", "month").all()

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
        top_markets=[
            {
                "category_id": r.id,
                "category_name": r.name,
                "market_id": r.id,
                "market_name": r.name,
                "total": float(r.total),
            }
            for r in top_cat
        ],
        top_categories=[
            {
                "category_id": r.id,
                "category_name": r.name,
                "market_id": r.id,
                "market_name": r.name,
                "total": float(r.total),
            }
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
            {"year": int(r.year), "month": int(r.month),
             "total": float(r.total), "count": r.count}
            for r in monthly
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

    cust_ids = [c.id for c in customers]

    # ── Batch: all active invoices for these customers (1 query) ─────────────
    all_invoices = (
        db.query(models.Invoice)
        .filter(
            models.Invoice.customer_id.in_(cust_ids),
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
            models.Invoice.customer_id.in_(cust_ids),
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
    for r in prod_rows:
        top_prod_by_cust[r.customer_id].append({
            "product_id": r.product_id, "product_name": r.product_name,
            "qty": float(r.qty), "value": float(r.value),
        })
    for cid in top_prod_by_cust:
        top_prod_by_cust[cid].sort(key=lambda x: x["value"], reverse=True)
        top_prod_by_cust[cid] = top_prod_by_cust[cid][:10]

    # ── Build result list in Python ───────────────────────────────────────────
    results = []
    for c in customers:
        invoices = inv_by_cust[c.id]
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
            customer_id=c.id,
            customer_name=c.customer_name,
            top_products=top_prod_by_cust[c.id],
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
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    selected_market = market_id or category_id
    if selected_market:
        q = q.filter(models.Product.category_id == selected_market)
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
    q_base = db.query(models.Quotation)
    if date_from:
        q_base = q_base.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        q_base = q_base.filter(models.Quotation.quotation_date <= date_to)

    quot_status_rows = (
        q_base.with_entities(
            models.Quotation.status,
            func.count(models.Quotation.id).label("cnt"),
            func.sum(models.Quotation.total_amount).label("val"),
        )
        .group_by(models.Quotation.status)
        .all()
    )
    qmap: dict = {}
    for r in quot_status_rows:
        qmap[r.status.value] = {"cnt": r.cnt, "val": float(r.val or 0)}

    q_total     = sum(v["cnt"] for v in qmap.values())
    q_draft     = qmap.get("draft", {}).get("cnt", 0)
    q_pending   = qmap.get("pending_approval", {}).get("cnt", 0)
    q_approved  = qmap.get("approved", {}).get("cnt", 0)
    q_rejected  = qmap.get("rejected", {}).get("cnt", 0)
    q_converted = qmap.get("converted", {}).get("cnt", 0)
    q_total_val = sum(v["val"] for v in qmap.values())
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
        conversion_rate=conv_r, total_value=q_total_val,
    )

    # ── Invoice stats ──────────────────────────────────────────────────────────
    i_base = db.query(models.Invoice)
    if date_from:
        i_base = i_base.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        i_base = i_base.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        i_base = i_base.filter(models.Invoice.id.in_(market_invoice_ids))

    inv_status_rows = (
        i_base.with_entities(
            models.Invoice.status,
            func.count(models.Invoice.id).label("cnt"),
            func.sum(models.Invoice.total_amount).label("billed"),
            func.sum(models.Invoice.amount_paid).label("collected"),
        )
        .group_by(models.Invoice.status)
        .all()
    )
    imap: dict = {}
    for r in inv_status_rows:
        imap[r.status.value] = {
            "cnt": r.cnt,
            "billed": float(r.billed or 0),
            "collected": float(r.collected or 0),
        }

    i_total     = sum(v["cnt"] for v in imap.values())
    i_active    = imap.get("active", {}).get("cnt", 0)
    i_partial   = imap.get("partially_paid", {}).get("cnt", 0)
    i_paid      = imap.get("paid", {}).get("cnt", 0) + imap.get("completed", {}).get("cnt", 0)
    i_cancelled = imap.get("cancelled", {}).get("cnt", 0)
    non_cancelled= i_total - i_cancelled
    paid_rate_v = round(i_paid / non_cancelled * 100, 2) if non_cancelled else 0
    cancel_rate_v= round(i_cancelled / i_total * 100, 2) if i_total else 0
    total_billed = sum(v["billed"]    for k, v in imap.items() if k != "cancelled")
    total_coll   = sum(v["collected"] for k, v in imap.items() if k != "cancelled")
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
    pmap: dict = {
        r.status.value: {"cnt": r.cnt, "total": float(r.total or 0)}
        for r in pay_rows
    }
    pay_stats = schemas.PaymentStats(
        total=sum(v["cnt"] for v in pmap.values()),
        pending=pmap.get("pending", {}).get("cnt", 0),
        confirmed=pmap.get("confirmed", {}).get("cnt", 0),
        voided=pmap.get("voided", {}).get("cnt", 0),
        failed=pmap.get("failed", {}).get("cnt", 0),
        total_amount=sum(v["total"] for v in pmap.values()),
        confirmed_amount=pmap.get("confirmed", {}).get("total", 0),
        pending_amount=pmap.get("pending", {}).get("total", 0),
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

    uqm: dict = defaultdict(dict)
    for r in uq_all:
        uqm[r.created_by][r.status.value] = r.cnt

    uim: dict = defaultdict(dict)
    for r in ui_all:
        uim[r.created_by][r.status.value] = {
            "cnt": r.cnt,
            "billed": float(r.billed or 0),
            "collected": float(r.collected or 0),
        }

    by_sales: list = []
    for u in all_users:
        uqmap = uqm[u.id]
        uimap = uim[u.id]
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
            func.sum(models.Quotation.total_amount).label("val"),
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

    mgr_map: dict = {}
    for r in manager_rows:
        if r.id not in mgr_map:
            mgr_map[r.id] = {
                "full_name": r.full_name, "username": r.username, "statuses": {}
            }
        mgr_map[r.id]["statuses"][r.status.value] = {
            "cnt": r.cnt, "val": float(r.val or 0)
        }

    # Top sales people per manager (batch: one query for all managers)
    top_sales_rows = (
        db.query(
            models.Quotation.approved_by,
            models.User.full_name,
            func.count(models.Quotation.id).label("cnt"),
            func.sum(models.Quotation.total_amount).label("val"),
        )
        .join(models.User, models.User.id == models.Quotation.created_by)
        .filter(
            models.Quotation.approved_by.in_(list(mgr_map.keys())),
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
    for r in top_sales_rows:
        top_sales_by_mgr[r.approved_by].append(
            {"name": r.full_name, "count": r.cnt, "value": float(r.val)}
        )

    by_manager: list = []
    for uid, m in mgr_map.items():
        s = m["statuses"]
        approved_cnt = s.get("approved", {}).get("cnt", 0) + s.get("converted", {}).get("cnt", 0)
        rejected_cnt = s.get("rejected", {}).get("cnt", 0)
        reviewed     = approved_cnt + rejected_cnt
        appr_r       = round(approved_cnt / reviewed * 100, 2) if reviewed else 0
        rej_r        = round(rejected_cnt / reviewed * 100, 2) if reviewed else 0
        rev_approved = sum(v["val"] for k, v in s.items() if k in ("approved", "converted"))

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
    role_q = (
        db.query(
            models.User.role,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
    )
    if date_from:
        role_q = role_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        role_q = role_q.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        role_q = role_q.filter(models.Invoice.id.in_(market_invoice_ids))
    role_rows = role_q.group_by(models.User.role).all()
    revenue_by_role = {r.role.value: float(r.total or 0) for r in role_rows}

    # ── Top customers + products (all-time or filtered) ────────────────────────
    tc_q = (
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
        tc_q = tc_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        tc_q = tc_q.filter(models.Invoice.invoice_date <= date_to)
    if market_invoice_ids is not None:
        tc_q = tc_q.filter(models.Invoice.id.in_(market_invoice_ids))
    top_cust_rows = (
        tc_q.group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(20).all()
    )

    tprod_q = (
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
        tprod_q = tprod_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        tprod_q = tprod_q.filter(models.Invoice.invoice_date <= date_to)
    if selected_market:
        tprod_q = tprod_q.filter(models.Product.category_id == selected_market)
    top_prod_rows = (
        tprod_q.group_by(models.Product.id, models.Product.product_name)
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
                "customer_id": r.id, "customer_name": r.customer_name,
                "orders": r.orders, "billed": float(r.billed),
                "collected": float(r.collected),
                "outstanding": float(r.billed) - float(r.collected),
                "collection_rate": round(
                    float(r.collected) / float(r.billed) * 100, 1
                ) if r.billed else 0,
            }
            for r in top_cust_rows
        ],
        top_products_revenue=[
            {
                "product_id": r.id, "product_name": r.product_name,
                "qty": float(r.qty), "revenue": float(r.revenue),
                "customers": r.customers,
            }
            for r in top_prod_rows
        ],
    )
