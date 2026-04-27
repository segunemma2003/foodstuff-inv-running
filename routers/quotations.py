from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_not_analyst, require_admin_or_manager
import models
import schemas
from utils import audit
from utils.pricing import get_active_rules, get_current_cost, calculate_item_price
from utils.number_gen import next_quotation_number
from utils.tasks import (
    generate_quotation_pdf_task,
    send_email_task,
    send_quotation_to_customer_task,
)
from utils.email import (
    tpl_quotation_submitted,
    tpl_quotation_approved,
    tpl_quotation_rejected,
)

router = APIRouter(prefix="/quotations", tags=["Quotations"])


# ─── Internal helpers ────────────────────────────────────────────────────────

def _calc_and_build_items(
    items_in: List[schemas.QuotationItemCreate],
    delivery_type: str,
    payment_term: str,
    db: Session,
) -> tuple[List[models.QuotationItem], Decimal]:
    rules = get_active_rules(db)
    built, total = [], Decimal("0")

    for it in items_in:
        cost = get_current_cost(it.product_id, db)
        if cost is None:
            product = db.query(models.Product).filter(models.Product.id == it.product_id).first()
            name = product.product_name if product else str(it.product_id)
            raise HTTPException(
                400,
                f"No active cost price for product '{name}' (id={it.product_id}). "
                "Upload a cost price first.",
            )
        pricing = calculate_item_price(cost, delivery_type, payment_term, rules)
        qty = Decimal(str(it.quantity))

        # Use manual override if provided, else calculated price
        if it.unit_price_override is not None:
            unit_price = Decimal(str(it.unit_price_override))
        else:
            unit_price = Decimal(str(pricing["unit_price"]))
        line_total = (qty * unit_price).quantize(Decimal("0.01"))
        total += line_total

        # Resolve UOM: explicit override > product default > None
        uom = it.uom
        if not uom:
            product = db.query(models.Product).filter(models.Product.id == it.product_id).first()
            uom = product.unit_of_measure if product else None

        built.append(models.QuotationItem(
            product_id=it.product_id,
            quantity=qty,
            uom=uom,
            cost_price=cost,
            supply_markup_pct=Decimal(str(pricing["supply_markup_pct"])),
            supply_markup_amount=Decimal(str(pricing["supply_markup_amount"])),
            delivery_markup_pct=Decimal(str(pricing["delivery_markup_pct"])),
            delivery_markup_amount=Decimal(str(pricing["delivery_markup_amount"])),
            payment_term_markup_pct=Decimal(str(pricing["payment_term_markup_pct"])),
            payment_term_markup_amount=Decimal(str(pricing["payment_term_markup_amount"])),
            unit_price=unit_price,
            line_total=line_total,
        ))
    return built, total


def _notify_approvers(db: Session, quotation: models.Quotation, created_by_name: str):
    """Queue email to all admin/manager users."""
    approvers = (
        db.query(models.User)
        .filter(
            models.User.is_active == True,
            models.User.role.in_([models.UserRole.admin, models.UserRole.manager]),
            models.User.email != None,
        )
        .all()
    )
    subject, html, text = tpl_quotation_submitted(
        quotation.quotation_number,
        quotation.customer.customer_name if quotation.customer else "",
        float(quotation.total_amount),
        created_by_name,
    )
    for approver in approvers:
        if approver.email:
            send_email_task.delay(approver.email, subject, html, text)


def _build_invoice_from_quotation(
    db: Session,
    quotation: models.Quotation,
    actor_user: models.User,
) -> models.Invoice:
    from datetime import timedelta
    from utils.number_gen import next_invoice_number

    if quotation.invoice:
        return quotation.invoice
    if quotation.status not in (models.QuotationStatus.approved, models.QuotationStatus.converted):
        raise HTTPException(400, "Only approved quotations can be converted to invoices")

    today = date.today()
    due = None
    if quotation.payment_term == "net_30":
        due = today + timedelta(days=30)
    elif quotation.payment_term == "net_60":
        due = today + timedelta(days=60)
    elif quotation.payment_term == "net_15":
        due = today + timedelta(days=15)

    invoice = models.Invoice(
        invoice_number=next_invoice_number(db),
        quotation_id=quotation.id,
        customer_id=quotation.customer_id,
        invoice_date=today,
        payment_term=quotation.payment_term,
        due_date=due,
        delivery_type=quotation.delivery_type,
        total_amount=quotation.total_amount,
        notes=quotation.notes,
        created_by=actor_user.id,
        status=models.InvoiceStatus.active,
    )
    db.add(invoice)
    db.flush()

    for qi in quotation.items:
        db.add(models.InvoiceItem(
            invoice_id=invoice.id,
            product_id=qi.product_id,
            quantity=qi.quantity,
            uom=qi.uom,
            cost_price=qi.cost_price,
            supply_markup_pct=qi.supply_markup_pct,
            supply_markup_amount=qi.supply_markup_amount,
            delivery_markup_pct=qi.delivery_markup_pct,
            delivery_markup_amount=qi.delivery_markup_amount,
            payment_term_markup_pct=qi.payment_term_markup_pct,
            payment_term_markup_amount=qi.payment_term_markup_amount,
            unit_price=qi.unit_price,
            line_total=qi.line_total,
        ))

    quotation.status = models.QuotationStatus.converted
    audit.log(
        db,
        models.AuditAction.convert,
        models.AuditEntity.quotation,
        quotation.id,
        actor_user.id,
        description=f"Converted {quotation.quotation_number} → {invoice.invoice_number}",
    )
    return invoice


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/calculate-price", response_model=List[schemas.PricePreviewResponse])
def preview_price(
    body: List[schemas.PricePreviewRequest],
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Preview pricing for a list of items before creating a quotation."""
    rules = get_active_rules(db)
    results = []
    for req in body:
        cost = get_current_cost(req.product_id, db)
        if cost is None:
            raise HTTPException(400, f"No cost price for product {req.product_id}")
        product = db.query(models.Product).filter(models.Product.id == req.product_id).first()
        pricing = calculate_item_price(cost, req.delivery_type, req.payment_term, rules)
        qty = float(req.quantity)
        results.append(schemas.PricePreviewResponse(
            product_id=req.product_id,
            product_name=product.product_name if product else "",
            quantity=qty,
            cost_price=float(cost),
            line_total=round(qty * pricing["unit_price"], 2),
            **pricing,
        ))
    return results


@router.get("", response_model=List[schemas.QuotationOut])
def list_quotations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    created_by: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Quotation)
    if status:
        q = q.filter(models.Quotation.status == status)
    if customer_id:
        q = q.filter(models.Quotation.customer_id == customer_id)
    if created_by:
        q = q.filter(models.Quotation.created_by == created_by)
    if date_from:
        q = q.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        q = q.filter(models.Quotation.quotation_date <= date_to)
    return q.order_by(models.Quotation.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=schemas.QuotationOut, status_code=201)
def create_quotation(
    body: schemas.QuotationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    customer = db.query(models.Customer).filter(
        models.Customer.id == body.customer_id,
        models.Customer.is_active == True,
    ).first()
    if not customer:
        raise HTTPException(404, "Active customer not found")
    if not body.items:
        raise HTTPException(400, "Quotation must have at least one item")

    items, total = _calc_and_build_items(body.items, body.delivery_type, body.payment_term, db)
    quotation = models.Quotation(
        quotation_number=next_quotation_number(db),
        customer_id=body.customer_id,
        quotation_date=body.quotation_date,
        delivery_type=body.delivery_type,
        payment_term=body.payment_term,
        notes=body.notes,
        total_amount=total,
        created_by=current_user.id,
        status=models.QuotationStatus.draft,
    )
    quotation.items = items
    db.add(quotation)
    db.flush()
    audit.log(db, models.AuditAction.create, models.AuditEntity.quotation, quotation.id,
               current_user.id, description=f"Created quotation {quotation.quotation_number}")
    db.commit()
    db.refresh(quotation)
    return quotation


@router.get("/{quotation_id}", response_model=schemas.QuotationOut)
def get_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    return q


@router.put("/{quotation_id}", response_model=schemas.QuotationOut)
def update_quotation(
    quotation_id: int,
    body: schemas.QuotationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status != models.QuotationStatus.draft:
        raise HTTPException(400, f"Only draft quotations can be edited (current: {q.status.value})")

    if body.delivery_type:
        q.delivery_type = body.delivery_type
    if body.payment_term:
        q.payment_term = body.payment_term
    if body.notes is not None:
        q.notes = body.notes

    if body.items is not None:
        for item in q.items:
            db.delete(item)
        delivery = body.delivery_type or q.delivery_type
        payment = body.payment_term or q.payment_term
        items, total = _calc_and_build_items(body.items, delivery, payment, db)
        for item in items:
            item.quotation_id = q.id
            db.add(item)
        q.total_amount = total

    audit.log(db, models.AuditAction.update, models.AuditEntity.quotation, q.id,
               current_user.id, description=f"Updated quotation {q.quotation_number}")
    db.commit()
    db.refresh(q)
    return q


@router.post("/{quotation_id}/submit", response_model=schemas.QuotationOut)
def submit_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status != models.QuotationStatus.draft:
        raise HTTPException(400, f"Only draft quotations can be submitted (current: {q.status.value})")

    q.status = models.QuotationStatus.pending_approval
    audit.log(db, models.AuditAction.submit, models.AuditEntity.quotation, q.id,
               current_user.id, description=f"Submitted quotation {q.quotation_number} for approval")
    db.commit()
    db.refresh(q)

    # Notify approvers — queued; API returns before email is sent
    _notify_approvers(db, q, current_user.full_name)
    return q


@router.post("/{quotation_id}/approve", response_model=schemas.QuotationOut)
def approve_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status != models.QuotationStatus.pending_approval:
        raise HTTPException(400, f"Only pending quotations can be approved (current: {q.status.value})")

    q.status = models.QuotationStatus.approved
    q.approved_by = current_user.id
    q.approved_at = datetime.utcnow()
    audit.log(db, models.AuditAction.approve, models.AuditEntity.quotation, q.id,
               current_user.id, description=f"Approved quotation {q.quotation_number}")
    invoice = _build_invoice_from_quotation(db, q, current_user)
    db.commit()
    db.refresh(q)
    db.refresh(invoice)

    # Notify creator — queued
    creator = db.query(models.User).filter(models.User.id == q.created_by).first()
    if creator and creator.email:
        subject, html, text = tpl_quotation_approved(
            q.quotation_number,
            q.customer.customer_name if q.customer else "",
        )
        send_email_task.delay(creator.email, subject, html, text)

    return q


@router.post("/{quotation_id}/reject", response_model=schemas.QuotationOut)
def reject_quotation(
    quotation_id: int,
    body: schemas.QuotationRejectRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status != models.QuotationStatus.pending_approval:
        raise HTTPException(400, f"Only pending quotations can be rejected (current: {q.status.value})")

    q.status = models.QuotationStatus.rejected
    q.rejection_reason = body.reason
    audit.log(db, models.AuditAction.reject, models.AuditEntity.quotation, q.id,
               current_user.id, description=f"Rejected quotation {q.quotation_number}: {body.reason}")
    db.commit()
    db.refresh(q)

    # Notify creator — queued
    creator = db.query(models.User).filter(models.User.id == q.created_by).first()
    if creator and creator.email:
        subject, html, text = tpl_quotation_rejected(
            q.quotation_number,
            q.customer.customer_name if q.customer else "",
            body.reason,
        )
        send_email_task.delay(creator.email, subject, html, text)

    return q


@router.get("/{quotation_id}/pdf")
def download_quotation_pdf(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Stream the quotation PDF directly (synchronous — no polling needed)."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from utils.pdf_generator import generate_quotation_pdf as gen_pdf

    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")

    pdf_bytes = gen_pdf(q)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{q.quotation_number}.pdf"'},
    )


@router.post("/{quotation_id}/send-to-customer", response_model=schemas.MessageResponse)
def send_quotation_to_customer(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    """Email the quotation PDF to the customer. Queued via Celery."""
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status == models.QuotationStatus.draft:
        raise HTTPException(400, "Submit the quotation before sending it to the customer")
    if not q.customer or not q.customer.email:
        raise HTTPException(400, "Customer has no email address on file")

    send_quotation_to_customer_task.delay(quotation_id)
    return schemas.MessageResponse(
        message=f"Quotation {q.quotation_number} queued for delivery to {q.customer.email}"
    )


@router.post("/{quotation_id}/generate-pdf", response_model=schemas.JobEnqueuedResponse,
             status_code=202)
def generate_quotation_pdf(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """
    Queue PDF generation. Returns a task_id immediately (< 5 ms).
    Poll GET /api/v1/jobs/{task_id} then download via GET /api/v1/jobs/{task_id}/download.
    """
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status == models.QuotationStatus.draft:
        raise HTTPException(400, "PDF is only available after the quotation is submitted")

    task = generate_quotation_pdf_task.delay(quotation_id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"PDF generation queued for {q.quotation_number}. "
                f"Poll /api/v1/jobs/{task.id} for status.",
    )


@router.post("/{quotation_id}/convert-to-invoice", response_model=schemas.InvoiceOut)
def convert_to_invoice(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    from utils.tasks import send_email_task
    from utils.email import tpl_invoice_created

    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.status != models.QuotationStatus.approved:
        raise HTTPException(400, "Only approved quotations can be converted to invoices")
    if q.invoice:
        raise HTTPException(400, f"Invoice {q.invoice.invoice_number} already exists for this quotation")
    invoice = _build_invoice_from_quotation(db, q, current_user)
    db.commit()
    db.refresh(invoice)

    # Notify creator — queued
    if current_user.email:
        subj, html, text = tpl_invoice_created(
            invoice.invoice_number, q.quotation_number,
            q.customer.customer_name if q.customer else "",
            float(invoice.total_amount),
        )
        send_email_task.delay(current_user.email, subj, html, text)

    return invoice
