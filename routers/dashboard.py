from typing import Optional
from datetime import date, timedelta, datetime
import os
import base64

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, String
from celery.result import AsyncResult
from celery_app import celery_app

from database import get_db
from dependencies import get_current_user
import models
import schemas
from utils.queue_events import log_queue_event
from utils.tasks import send_email_with_attachment_task

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
COST_OF_SALES_PRIMARY_RECIPIENT = os.getenv("COST_OF_SALES_RECIPIENT_EMAIL", "foodstuffstorepo@gmail.com")


def _not_cancelled_invoice_filter():
    return func.lower(models.Invoice.status.cast(String)) != "cancelled"


def _sales_in_range(db: Session, start: date, end: date) -> float:
    result = (
        db.query(func.sum(models.Invoice.total_amount))
        .filter(
            models.Invoice.invoice_date >= start,
            models.Invoice.invoice_date <= end,
            _not_cancelled_invoice_filter(),
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
        .filter(models.Invoice.invoice_date == today, _not_cancelled_invoice_filter())
        .scalar() or 0
    )

    sales_today = _sales_in_range(db, today, today)
    sales_week = _sales_in_range(db, week_start, today)
    sales_month = _sales_in_range(db, month_start, today)

    # Cost of sales = sum(cost_price * quantity) for non-cancelled invoices
    cos_month = (
        db.query(func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity))
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(
            models.Invoice.invoice_date >= month_start,
            models.Invoice.invoice_date <= today,
            _not_cancelled_invoice_filter(),
        )
        .scalar() or 0
    )
    cos_all = (
        db.query(func.sum(models.InvoiceItem.cost_price * models.InvoiceItem.quantity))
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(_not_cancelled_invoice_filter())
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
            _not_cancelled_invoice_filter(),
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
        .filter(_not_cancelled_invoice_filter())
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
        .filter(_not_cancelled_invoice_filter())
        .group_by(models.Product.id, models.Product.product_name)
        .order_by(func.sum(models.InvoiceItem.line_total).desc())
        .limit(5)
        .all()
    )

    # Delivery vs pickup
    delivery_rows = (
        db.query(models.Invoice.delivery_type, func.sum(models.Invoice.total_amount).label("total"))
        .filter(_not_cancelled_invoice_filter())
        .group_by(models.Invoice.delivery_type)
        .all()
    )
    delivery_vs_pickup = {r.delivery_type.value: float(r.total or 0) for r in delivery_rows}

    # Sales by payment term
    pt_rows = (
        db.query(models.Invoice.payment_term, func.sum(models.Invoice.total_amount).label("total"))
        .filter(_not_cancelled_invoice_filter())
        .group_by(models.Invoice.payment_term)
        .all()
    )
    sales_by_pt = {r.payment_term: float(r.total or 0) for r in pt_rows}

    # Recent
    recent_invoices = (
        db.query(models.Invoice)
        .filter(_not_cancelled_invoice_filter())
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


# ── Cost of Sales detail ──────────────────────────────────────────────────────

class CostOfSalesEmailRequest(BaseModel):
    date_from:   Optional[date] = None
    date_to:     Optional[date] = None
    customer_id: Optional[int]  = None
    product_id:  Optional[int]  = None
    additional_emails: Optional[list[EmailStr]] = None


@router.get("/cost-of-sales")
def cost_of_sales_detail(
    date_from:   Optional[date] = None,
    date_to:     Optional[date] = None,
    customer_id: Optional[int]  = None,
    product_id:  Optional[int]  = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    item_q = (
        db.query(
            models.InvoiceItem.product_id,
            models.Product.product_name,
            func.sum(models.InvoiceItem.quantity).label("qty"),
            func.sum(
                models.InvoiceItem.cost_price * models.InvoiceItem.quantity
            ).label("cost"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
        )
        .join(models.Product, models.Product.id == models.InvoiceItem.product_id)
        .join(models.Invoice, models.Invoice.id == models.InvoiceItem.invoice_id)
        .filter(_not_cancelled_invoice_filter())
    )
    if date_from:
        item_q = item_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        item_q = item_q.filter(models.Invoice.invoice_date <= date_to)
    if customer_id:
        item_q = item_q.filter(models.Invoice.customer_id == customer_id)
    if product_id:
        item_q = item_q.filter(models.InvoiceItem.product_id == product_id)

    product_rows = (
        item_q
        .group_by(models.InvoiceItem.product_id, models.Product.product_name)
        .order_by(func.sum(
            models.InvoiceItem.cost_price * models.InvoiceItem.quantity
        ).desc())
        .all()
    )

    inv_q = (
        db.query(
            models.Invoice.id,
            models.Invoice.invoice_number,
            models.Invoice.invoice_date,
            models.Customer.customer_name,
            func.sum(
                models.InvoiceItem.cost_price * models.InvoiceItem.quantity
            ).label("cost"),
            func.sum(models.InvoiceItem.line_total).label("revenue"),
        )
        .join(models.InvoiceItem, models.InvoiceItem.invoice_id == models.Invoice.id)
        .join(models.Customer, models.Customer.id == models.Invoice.customer_id)
        .filter(_not_cancelled_invoice_filter())
    )
    if date_from:
        inv_q = inv_q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        inv_q = inv_q.filter(models.Invoice.invoice_date <= date_to)
    if customer_id:
        inv_q = inv_q.filter(models.Invoice.customer_id == customer_id)
    if product_id:
        inv_q = inv_q.filter(models.InvoiceItem.product_id == product_id)

    invoice_rows = (
        inv_q
        .group_by(
            models.Invoice.id, models.Invoice.invoice_number,
            models.Invoice.invoice_date, models.Customer.customer_name,
        )
        .order_by(models.Invoice.invoice_date.desc())
        .all()
    )

    total_cost    = sum(float(r.cost or 0)    for r in product_rows)
    total_revenue = sum(float(r.revenue or 0) for r in product_rows)
    gross_profit  = total_revenue - total_cost
    gross_margin  = round(gross_profit / total_revenue * 100, 2) if total_revenue else 0

    return {
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
                "qty": float(r.qty),
                "unit_cost_price": (float(r.cost or 0) / float(r.qty)) if float(r.qty or 0) > 0 else 0,
                "cost": float(r.cost or 0),
                "revenue": float(r.revenue or 0),
                "gross_profit": float(r.revenue or 0) - float(r.cost or 0),
                "margin_pct": round(
                    (float(r.revenue or 0) - float(r.cost or 0))
                    / float(r.revenue) * 100, 2
                ) if r.revenue else 0,
            }
            for r in product_rows
        ],
        "by_invoice": [
            {
                "invoice_id": r.id,
                "invoice_number": r.invoice_number,
                "invoice_date": str(r.invoice_date),
                "customer_name": r.customer_name,
                "cost": float(r.cost or 0),
                "revenue": float(r.revenue or 0),
                "gross_profit": float(r.revenue or 0) - float(r.cost or 0),
                "margin_pct": round(
                    (float(r.revenue or 0) - float(r.cost or 0))
                    / float(r.revenue) * 100, 2
                ) if r.revenue else 0,
            }
            for r in invoice_rows
        ],
    }


@router.post("/cost-of-sales/email")
def email_cost_of_sales_report(
    body: CostOfSalesEmailRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from utils.pdf_generator import generate_cost_of_sales_pdf

    data = cost_of_sales_detail(
        date_from=body.date_from,
        date_to=body.date_to,
        customer_id=body.customer_id,
        product_id=body.product_id,
        db=db,
        _=current_user,
    )
    s   = data["summary"]
    rows_html = "".join(
        f"<tr style='background:{'#f9f9f9' if i%2 else '#fff'}'>"
        f"<td style='padding:6px 10px'>{r['invoice_number']}</td>"
        f"<td style='padding:6px 10px'>{r['invoice_date']}</td>"
        f"<td style='padding:6px 10px'>{r['customer_name']}</td>"
        f"<td style='padding:6px 10px;text-align:right'>&#8358;{r['cost']:,.2f}</td>"
        f"<td style='padding:6px 10px;text-align:right'>&#8358;{r['revenue']:,.2f}</td>"
        f"<td style='padding:6px 10px;text-align:right'>&#8358;{r['gross_profit']:,.2f}</td>"
        f"<td style='padding:6px 10px;text-align:right'>{r['margin_pct']:.1f}%</td>"
        f"</tr>"
        for i, r in enumerate(data["by_invoice"])
    )
    date_label = ""
    if body.date_from or body.date_to:
        date_label = f" ({body.date_from or '—'} to {body.date_to or '—'})"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:700px">
      <h2 style="color:#1e8449">Cost of Sales Report{date_label}</h2>
      <table style="border-collapse:collapse;width:100%;margin-bottom:24px">
        <tr style="background:#eafaf1">
          <td style="padding:10px;font-weight:bold">Total Cost</td>
          <td style="padding:10px">&#8358;{s['total_cost']:,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px;font-weight:bold">Total Revenue</td>
          <td style="padding:10px">&#8358;{s['total_revenue']:,.2f}</td>
        </tr>
        <tr style="background:#eafaf1">
          <td style="padding:10px;font-weight:bold">Gross Profit</td>
          <td style="padding:10px;color:#1e8449;font-weight:bold">&#8358;{s['gross_profit']:,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px;font-weight:bold">Gross Margin</td>
          <td style="padding:10px">{s['gross_margin_pct']:.1f}%</td>
        </tr>
      </table>
      <h3 style="color:#1e8449">Breakdown by Invoice</h3>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="background:#1e8449;color:#fff">
            <th style="padding:8px 10px;text-align:left">Invoice</th>
            <th style="padding:8px 10px;text-align:left">Date</th>
            <th style="padding:8px 10px;text-align:left">Customer</th>
            <th style="padding:8px 10px;text-align:right">Cost</th>
            <th style="padding:8px 10px;text-align:right">Revenue</th>
            <th style="padding:8px 10px;text-align:right">Gross Profit</th>
            <th style="padding:8px 10px;text-align:right">Margin</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <hr style="margin-top:24px"/>
      <p style="font-size:12px;color:#888">
        Sent by {current_user.full_name} — Foodstuff Store Internal System
      </p>
    </div>"""
    text = (
        f"Cost of Sales Report{date_label}\n\n"
        f"Total Cost:    ₦{s['total_cost']:,.2f}\n"
        f"Total Revenue: ₦{s['total_revenue']:,.2f}\n"
        f"Gross Profit:  ₦{s['gross_profit']:,.2f}\n"
        f"Gross Margin:  {s['gross_margin_pct']:.1f}%\n"
    )
    pdf_bytes = generate_cost_of_sales_pdf(data, title_suffix=date_label)
    recipients: list[str] = [COST_OF_SALES_PRIMARY_RECIPIENT]
    if body.additional_emails:
        recipients.extend([str(e).strip() for e in body.additional_emails if str(e).strip()])
    recipients = list(dict.fromkeys(recipients))

    task = send_email_with_attachment_task.delay(
        recipients,
        f"Cost of Sales Report{date_label} — Foodstuff Store",
        html,
        text,
        "cost_of_sales.pdf",
        "application/pdf",
        base64.b64encode(pdf_bytes).decode("utf-8"),
    )
    log_queue_event(
        db,
        task_id=task.id,
        event_type="cost_of_sales_email",
        title=f"Send cost of sales report{date_label}",
        requested_by=current_user.id if current_user else None,
        metadata={"recipients": recipients, "customer_id": body.customer_id, "product_id": body.product_id},
    )
    return {"message": f"Report queued for {len(recipients)} recipient(s)"}


@router.post("/cost-of-sales/upload-to-make")
def upload_cost_of_sales_to_make(
    body: CostOfSalesEmailRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Upload-to-make action for Cost of Sales.
    Uses the Cost of Sales recipient flow (primary + additional emails).
    """
    return email_cost_of_sales_report(body=body, db=db, current_user=current_user)


@router.get("/queue-events", response_model=list[schemas.QueueEventOut])
def list_queue_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    queue_event_query = db.query(models.QueueEvent)
    if event_type:
        queue_event_query = queue_event_query.filter(models.QueueEvent.event_type == event_type)
    events = queue_event_query.order_by(models.QueueEvent.created_at.desc()).limit(limit).all()

    out: list[schemas.QueueEventOut] = []
    for event in events:
        task = AsyncResult(event.task_id, app=celery_app)
        item = schemas.QueueEventOut.model_validate(event).model_dump()
        item["status"] = task.state
        item["delivery_outcomes"] = None
        task_result = task.result if task.state == "SUCCESS" else None
        if isinstance(task_result, dict):
            outcomes = task_result.get("delivery_outcomes")
            if isinstance(outcomes, list):
                item["delivery_outcomes"] = outcomes
        if task.state == "FAILURE":
            item["error"] = str(task.info)
        out.append(schemas.QueueEventOut(**item))
    return out


@router.get("/cost-of-sales/pdf")
def download_cost_of_sales_pdf(
    date_from:   Optional[date] = None,
    date_to:     Optional[date] = None,
    customer_id: Optional[int]  = None,
    product_id:  Optional[int]  = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from utils.pdf_generator import generate_cost_of_sales_pdf

    data = cost_of_sales_detail(
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        product_id=product_id,
        db=db,
        _=current_user,
    )
    label = ""
    if date_from or date_to:
        label = f" ({date_from or 'start'} to {date_to or 'end'})"
    pdf_bytes = generate_cost_of_sales_pdf(data, title_suffix=label)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cost_of_sales.pdf"'},
    )
