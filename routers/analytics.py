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


@router.get("/comprehensive", response_model=schemas.ComprehensiveStats)
def comprehensive_stats(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """All-in-one stats: quotation funnel, invoice breakdown, payment collection,
    per-sales-person, per-manager."""

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
    conv_r      = round(q_converted / (q_approved + q_converted) * 100, 2) if (q_approved + q_converted) else 0

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

    i_total       = sum(v["cnt"] for v in imap.values())
    i_active      = imap.get("active", {}).get("cnt", 0)
    i_partial     = imap.get("partially_paid", {}).get("cnt", 0)
    i_paid        = imap.get("paid", {}).get("cnt", 0)
    i_cancelled   = imap.get("cancelled", {}).get("cnt", 0)
    non_cancelled = i_total - i_cancelled
    paid_rate_v   = round(i_paid / non_cancelled * 100, 2) if non_cancelled else 0
    cancel_rate_v = round(i_cancelled / i_total * 100, 2) if i_total else 0
    total_billed  = sum(v["billed"] for k, v in imap.items() if k != "cancelled")
    total_coll    = sum(v["collected"] for k, v in imap.items() if k != "cancelled")
    total_out     = total_billed - total_coll
    coll_rate     = round(total_coll / total_billed * 100, 2) if total_billed else 0

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
        .group_by(models.Payment.status)
        .all()
    )
    pmap: dict = {r.status.value: {"cnt": r.cnt, "total": float(r.total or 0)} for r in pay_rows}
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

    # ── Per-sales-person stats ─────────────────────────────────────────────────
    all_users = db.query(models.User).filter(models.User.is_active == True).all()
    by_sales: list = []
    for u in all_users:
        # Quotations
        uq_base = db.query(models.Quotation).filter(models.Quotation.created_by == u.id)
        if date_from:
            uq_base = uq_base.filter(models.Quotation.quotation_date >= date_from)
        if date_to:
            uq_base = uq_base.filter(models.Quotation.quotation_date <= date_to)
        uq_rows = (
            uq_base.with_entities(
                models.Quotation.status,
                func.count(models.Quotation.id).label("cnt"),
            )
            .group_by(models.Quotation.status)
            .all()
        )
        uqm: dict = {r.status.value: r.cnt for r in uq_rows}
        uq_total   = sum(uqm.values())
        uq_draft   = uqm.get("draft", 0)
        uq_pending = uqm.get("pending_approval", 0)
        uq_appr    = uqm.get("approved", 0)
        uq_rej     = uqm.get("rejected", 0)
        uq_conv    = uqm.get("converted", 0)
        uq_sub     = uq_pending + uq_appr + uq_rej + uq_conv
        uq_appr_r  = round((uq_appr + uq_conv) / uq_sub * 100, 2) if uq_sub else 0
        uq_conv_r  = round(uq_conv / (uq_appr + uq_conv) * 100, 2) if (uq_appr + uq_conv) else 0

        # Invoices
        ui_base = db.query(models.Invoice).filter(models.Invoice.created_by == u.id)
        if date_from:
            ui_base = ui_base.filter(models.Invoice.invoice_date >= date_from)
        if date_to:
            ui_base = ui_base.filter(models.Invoice.invoice_date <= date_to)
        ui_rows = (
            ui_base.with_entities(
                models.Invoice.status,
                func.count(models.Invoice.id).label("cnt"),
                func.sum(models.Invoice.total_amount).label("billed"),
                func.sum(models.Invoice.amount_paid).label("collected"),
            )
            .group_by(models.Invoice.status)
            .all()
        )
        uim: dict = {}
        for r in ui_rows:
            uim[r.status.value] = {
                "cnt": r.cnt,
                "billed": float(r.billed or 0),
                "collected": float(r.collected or 0),
            }
        ui_total    = sum(v["cnt"] for v in uim.values())
        ui_paid     = uim.get("paid", {}).get("cnt", 0)
        ui_partial  = uim.get("partially_paid", {}).get("cnt", 0)
        ui_active   = uim.get("active", {}).get("cnt", 0)
        ui_cancel   = uim.get("cancelled", {}).get("cnt", 0)
        ui_billed   = sum(v["billed"] for k, v in uim.items() if k != "cancelled")
        ui_coll     = sum(v["collected"] for k, v in uim.items() if k != "cancelled")
        ui_out      = ui_billed - ui_coll
        ui_coll_r   = round(ui_coll / ui_billed * 100, 2) if ui_billed else 0
        ui_avg      = ui_billed / (ui_total - ui_cancel) if (ui_total - ui_cancel) else 0

        if uq_total == 0 and ui_total == 0:
            continue  # Skip users with no activity

        by_sales.append(schemas.SalesPersonStats(
            user_id=u.id, full_name=u.full_name, username=u.username, role=u.role.value,
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

    # ── Per-manager stats (users who approve quotations) ───────────────────────
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
        .group_by(models.User.id, models.User.full_name, models.User.username, models.Quotation.status)
        .all()
    )

    mgr_map: dict = {}
    for r in manager_rows:
        if r.id not in mgr_map:
            mgr_map[r.id] = {"full_name": r.full_name, "username": r.username, "statuses": {}}
        mgr_map[r.id]["statuses"][r.status.value] = {"cnt": r.cnt, "val": float(r.val or 0)}

    by_manager: list = []
    for uid, m in mgr_map.items():
        s = m["statuses"]
        approved_cnt  = s.get("approved", {}).get("cnt", 0) + s.get("converted", {}).get("cnt", 0)
        rejected_cnt  = s.get("rejected", {}).get("cnt", 0)
        reviewed      = approved_cnt + rejected_cnt
        appr_r        = round(approved_cnt / reviewed * 100, 2) if reviewed else 0
        rej_r         = round(rejected_cnt / reviewed * 100, 2) if reviewed else 0
        rev_approved  = sum(v["val"] for k, v in s.items() if k in ("approved", "converted"))

        # Top sales people whose quotations this manager approved
        top_sales_rows = (
            db.query(
                models.User.full_name,
                func.count(models.Quotation.id).label("cnt"),
                func.sum(models.Quotation.total_amount).label("val"),
            )
            .join(models.Quotation, models.Quotation.created_by == models.User.id)
            .filter(
                models.Quotation.approved_by == uid,
                models.Quotation.status.in_([
                    models.QuotationStatus.approved,
                    models.QuotationStatus.converted,
                ]),
            )
            .group_by(models.User.id, models.User.full_name)
            .order_by(func.sum(models.Quotation.total_amount).desc())
            .limit(5)
            .all()
        )

        by_manager.append(schemas.ManagerStats(
            user_id=uid, full_name=m["full_name"], username=m["username"],
            reviewed_total=reviewed, approved_count=approved_cnt, rejected_count=rejected_cnt,
            approval_rate=appr_r, rejection_rate=rej_r, revenue_approved=rev_approved,
            top_sales=[{"name": r.full_name, "count": r.cnt, "value": float(r.val)} for r in top_sales_rows],
        ))
    by_manager.sort(key=lambda x: x.revenue_approved, reverse=True)

    # ── Revenue by role ────────────────────────────────────────────────────────
    role_rows = (
        db.query(
            models.User.role,
            func.sum(models.Invoice.total_amount).label("total"),
        )
        .join(models.Invoice, models.Invoice.created_by == models.User.id)
        .filter(models.Invoice.status.in_([
            models.InvoiceStatus.active,
            models.InvoiceStatus.partially_paid,
            models.InvoiceStatus.paid,
        ]))
        .group_by(models.User.role)
        .all()
    )
    revenue_by_role = {r.role.value: float(r.total or 0) for r in role_rows}

    # ── Top customers + products (all-time) ────────────────────────────────────
    top_cust_rows = (
        db.query(
            models.Customer.id, models.Customer.customer_name,
            func.count(func.distinct(models.Invoice.id)).label("orders"),
            func.sum(models.Invoice.total_amount).label("billed"),
            func.sum(models.Invoice.amount_paid).label("collected"),
        )
        .join(models.Invoice, models.Invoice.customer_id == models.Customer.id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
        .group_by(models.Customer.id, models.Customer.customer_name)
        .order_by(func.sum(models.Invoice.total_amount).desc())
        .limit(20)
        .all()
    )
    top_prod_rows = (
        db.query(
            models.Product.id, models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
            func.count(func.distinct(models.Invoice.customer_id)).label("customers"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.product_id == models.Product.id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(models.Invoice.status != models.InvoiceStatus.cancelled)
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(20)
        .all()
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
                "collection_rate": round(float(r.collected) / float(r.billed) * 100, 1) if r.billed else 0,
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
