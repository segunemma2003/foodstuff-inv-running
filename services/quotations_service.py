"""Quotation domain business logic and orchestration."""

from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
import base64

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit
from utils.pricing import get_active_rules, get_current_cost, calculate_item_price
from utils.number_gen import next_quotation_number
from utils.tasks import (
    generate_quotation_pdf_task,
    send_email_task,
    send_quotation_to_customer_task,
    send_email_with_attachment_task,
)
from utils.queue_events import log_queue_event
from utils.email import (
    tpl_quotation_submitted,
    tpl_quotation_approved,
    tpl_quotation_rejected,
)

INVOICE_PRIMARY_RECIPIENT = "foodstuffstoreinvoices@gmail.com"


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
            if product and not product.is_active:
                raise HTTPException(
                    400,
                    f"Product '{name}' is deactivated and cannot be used.",
                )
            raise HTTPException(
                400,
                f"No active cost price for product '{name}' (id={it.product_id}). "
                "Upload a cost price first.",
            )
        pricing = calculate_item_price(cost, delivery_type, payment_term, rules)
        qty = Decimal(str(it.quantity))

        if it.unit_price_override is not None:
            unit_price = Decimal(str(it.unit_price_override))
        else:
            unit_price = Decimal(str(pricing["unit_price"]))
        line_total = (qty * unit_price).quantize(Decimal("0.01"))
        total += line_total

        uom = it.uom
        if not uom:
            product = db.query(models.Product).filter(models.Product.id == it.product_id).first()
            if product and not product.is_active:
                raise HTTPException(
                    400,
                    f"Product '{product.product_name}' is deactivated and cannot be used.",
                )
            uom = product.unit_of_measure if product else None

        built.append(
            models.QuotationItem(
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
            )
        )
    return built, total


def _notify_approvers(db: Session, quotation: models.Quotation, created_by_name: str):
    approvers = (
        db.query(models.User)
        .filter(
            models.User.is_active == True,
            models.User.role.in_([models.UserRole.admin, models.UserRole.manager]),
            models.User.email.is_not(None),
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
    elif quotation.payment_term == "net_90":
        due = today + timedelta(days=90)

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
        db.add(
            models.InvoiceItem(
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
            )
        )

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


def preview_price(body: List[schemas.PricePreviewRequest], db: Session) -> List[schemas.PricePreviewResponse]:
    rules = get_active_rules(db)
    results = []
    for req in body:
        cost = get_current_cost(req.product_id, db)
        if cost is None:
            raise HTTPException(400, f"No cost price for product {req.product_id}")
        product = db.query(models.Product).filter(models.Product.id == req.product_id).first()
        if product and not product.is_active:
            raise HTTPException(400, f"Product '{product.product_name}' is deactivated and cannot be used.")
        pricing = calculate_item_price(cost, req.delivery_type, req.payment_term, rules)
        qty = float(req.quantity)
        results.append(
            schemas.PricePreviewResponse(
                product_id=req.product_id,
                product_name=product.product_name if product else "",
                quantity=qty,
                cost_price=float(cost),
                line_total=round(qty * pricing["unit_price"], 2),
                **pricing,
            )
        )
    return results


def list_quotations(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    created_by: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[models.Quotation]:
    quotation_query = db.query(models.Quotation)
    if status:
        quotation_query = quotation_query.filter(models.Quotation.status == status)
    if customer_id:
        quotation_query = quotation_query.filter(models.Quotation.customer_id == customer_id)
    if created_by:
        quotation_query = quotation_query.filter(models.Quotation.created_by == created_by)
    if date_from:
        quotation_query = quotation_query.filter(models.Quotation.quotation_date >= date_from)
    if date_to:
        quotation_query = quotation_query.filter(models.Quotation.quotation_date <= date_to)
    return quotation_query.order_by(models.Quotation.created_at.desc()).offset(skip).limit(limit).all()


def create_quotation(db: Session, body: schemas.QuotationCreate, current_user: models.User) -> models.Quotation:
    customer = (
        db.query(models.Customer)
        .filter(
            models.Customer.id == body.customer_id,
            models.Customer.is_active == True,
        )
        .first()
    )
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
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Created quotation {quotation.quotation_number}",
    )
    db.commit()
    db.refresh(quotation)
    return quotation


def bulk_delete_quotations(
    db: Session, body: schemas.BulkIdsRequest, current_user: models.User
) -> schemas.BulkDeleteResult:
    result = schemas.BulkDeleteResult()
    for qid in body.ids:
        quotation = db.query(models.Quotation).filter(models.Quotation.id == qid).first()
        if not quotation:
            result.failed.append({"id": qid, "detail": "Quotation not found"})
            continue
        linked = db.query(models.Invoice).filter(models.Invoice.quotation_id == quotation.id).first()
        if linked:
            result.failed.append(
                {
                    "id": qid,
                    "detail": f"Converted to invoice {linked.invoice_number}; delete that invoice first",
                }
            )
            continue
        num = quotation.quotation_number
        audit.log(
            db,
            models.AuditAction.delete,
            models.AuditEntity.quotation,
            quotation.id,
            current_user.id,
            description=f"Deleted quotation {num}",
        )
        db.delete(quotation)
        result.deleted += 1
    db.commit()
    return result


def delete_quotation(db: Session, quotation_id: int, current_user: models.User) -> schemas.MessageResponse:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    linked = db.query(models.Invoice).filter(models.Invoice.quotation_id == quotation.id).first()
    if linked:
        raise HTTPException(
            400,
            f"This quotation was converted to invoice {linked.invoice_number}. Delete that invoice first.",
        )
    num = quotation.quotation_number
    audit.log(
        db,
        models.AuditAction.delete,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Deleted quotation {num}",
    )
    db.delete(quotation)
    db.commit()
    return schemas.MessageResponse(message=f"Quotation {num} deleted")


def get_quotation(db: Session, quotation_id: int) -> models.Quotation:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    return quotation


def update_quotation(
    db: Session,
    quotation_id: int,
    body: schemas.QuotationUpdate,
    current_user: models.User,
) -> models.Quotation:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status != models.QuotationStatus.draft:
        raise HTTPException(400, f"Only draft quotations can be edited (current: {quotation.status.value})")

    if body.delivery_type:
        quotation.delivery_type = body.delivery_type
    if body.payment_term:
        quotation.payment_term = body.payment_term
    if body.notes is not None:
        quotation.notes = body.notes

    if body.items is not None:
        for item in quotation.items:
            db.delete(item)
        delivery = body.delivery_type or quotation.delivery_type
        payment = body.payment_term or quotation.payment_term
        items, total = _calc_and_build_items(body.items, delivery, payment, db)
        for item in items:
            item.quotation_id = quotation.id
            db.add(item)
        quotation.total_amount = total

    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Updated quotation {quotation.quotation_number}",
    )
    db.commit()
    db.refresh(quotation)
    return quotation


def submit_quotation(db: Session, quotation_id: int, current_user: models.User) -> models.Quotation:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status != models.QuotationStatus.draft:
        raise HTTPException(400, f"Only draft quotations can be submitted (current: {quotation.status.value})")

    quotation.status = models.QuotationStatus.pending_approval
    audit.log(
        db,
        models.AuditAction.submit,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Submitted quotation {quotation.quotation_number} for approval",
    )
    db.commit()
    db.refresh(quotation)
    _notify_approvers(db, quotation, current_user.full_name)
    return quotation


def approve_quotation(db: Session, quotation_id: int, current_user: models.User) -> models.Quotation:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status != models.QuotationStatus.pending_approval:
        raise HTTPException(400, f"Only pending quotations can be approved (current: {quotation.status.value})")

    quotation.status = models.QuotationStatus.approved
    quotation.approved_by = current_user.id
    quotation.approved_at = datetime.utcnow()
    audit.log(
        db,
        models.AuditAction.approve,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Approved quotation {quotation.quotation_number}",
    )
    invoice = _build_invoice_from_quotation(db, quotation, current_user)
    db.commit()
    db.refresh(quotation)
    db.refresh(invoice)

    creator = db.query(models.User).filter(models.User.id == quotation.created_by).first()
    if creator and creator.email:
        subject, html, text = tpl_quotation_approved(
            quotation.quotation_number,
            quotation.customer.customer_name if quotation.customer else "",
        )
        send_email_task.delay(creator.email, subject, html, text)

    return quotation


def reject_quotation(
    db: Session,
    quotation_id: int,
    body: schemas.QuotationRejectRequest,
    current_user: models.User,
) -> models.Quotation:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status != models.QuotationStatus.pending_approval:
        raise HTTPException(400, f"Only pending quotations can be rejected (current: {quotation.status.value})")

    quotation.status = models.QuotationStatus.rejected
    quotation.rejection_reason = body.reason
    audit.log(
        db,
        models.AuditAction.reject,
        models.AuditEntity.quotation,
        quotation.id,
        current_user.id,
        description=f"Rejected quotation {quotation.quotation_number}: {body.reason}",
    )
    db.commit()
    db.refresh(quotation)

    creator = db.query(models.User).filter(models.User.id == quotation.created_by).first()
    if creator and creator.email:
        subject, html, text = tpl_quotation_rejected(
            quotation.quotation_number,
            quotation.customer.customer_name if quotation.customer else "",
            body.reason,
        )
        send_email_task.delay(creator.email, subject, html, text)

    return quotation


def download_quotation_pdf(db: Session, quotation_id: int) -> StreamingResponse:
    from io import BytesIO
    from utils.pdf_generator import generate_quotation_pdf as gen_pdf

    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")

    pdf_bytes = gen_pdf(quotation)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quotation.quotation_number}.pdf"'},
    )


def send_quotation_to_customer(
    db: Session, quotation_id: int, current_user: models.User
) -> schemas.MessageResponse:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status == models.QuotationStatus.draft:
        raise HTTPException(400, "Submit the quotation before sending it to the customer")
    if not quotation.customer or not quotation.customer.email:
        raise HTTPException(400, "Customer has no email address on file")

    task = send_quotation_to_customer_task.delay(quotation_id)
    log_queue_event(
        db,
        task_id=task.id,
        event_type="quotation_email",
        title=f"Send quotation email {quotation.quotation_number}",
        requested_by=current_user.id if current_user else None,
        metadata={"quotation_id": quotation.id, "customer_email": quotation.customer.email if quotation.customer else None},
    )
    return schemas.MessageResponse(
        message=f"Quotation {quotation.quotation_number} queued for delivery to {quotation.customer.email}"
    )


def upload_quotation_to_make(
    db: Session,
    quotation_id: int,
    additional_emails: Optional[List[str]],
    current_user: models.User,
) -> schemas.MessageResponse:
    from utils.pdf_generator import generate_quotation_pdf as gen_pdf

    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status == models.QuotationStatus.draft:
        raise HTTPException(400, "Submit the quotation before sending it")

    pdf_bytes = gen_pdf(quotation)
    recipients: List[str] = [INVOICE_PRIMARY_RECIPIENT]
    if additional_emails:
        recipients.extend([e.strip() for e in additional_emails if e and e.strip()])
    recipients = list(dict.fromkeys(recipients))
    if not recipients:
        raise HTTPException(400, "No email addresses to send to")

    task = send_email_with_attachment_task.delay(
        recipients,
        f"Quotation {quotation.quotation_number}",
        f"<p>Please find attached quotation <strong>{quotation.quotation_number}</strong>.</p>",
        f"Please find attached quotation {quotation.quotation_number}.",
        f"{quotation.quotation_number}.pdf",
        "application/pdf",
        base64.b64encode(pdf_bytes).decode("utf-8"),
    )
    log_queue_event(
        db,
        task_id=task.id,
        event_type="quotation_upload_to_make",
        title=f"Upload quotation to make {quotation.quotation_number}",
        requested_by=current_user.id if current_user else None,
        metadata={"quotation_id": quotation.id, "recipients": recipients},
    )

    return schemas.MessageResponse(message=f"Quotation queued for {len(recipients)} recipient(s)")


def generate_quotation_pdf(
    db: Session,
    quotation_id: int,
    current_user: models.User,
) -> schemas.JobEnqueuedResponse:
    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status == models.QuotationStatus.draft:
        raise HTTPException(400, "PDF is only available after the quotation is submitted")

    task = generate_quotation_pdf_task.delay(quotation_id)
    log_queue_event(
        db,
        task_id=task.id,
        event_type="quotation_pdf",
        title=f"Generate quotation PDF {quotation.quotation_number}",
        requested_by=current_user.id if current_user else None,
        metadata={"quotation_id": quotation.id},
    )
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"PDF generation queued for {quotation.quotation_number}. "
        f"Poll /api/v1/jobs/{task.id} for status.",
    )


def convert_to_invoice(db: Session, quotation_id: int, current_user: models.User) -> models.Invoice:
    from utils.email import tpl_invoice_created

    quotation = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(404, "Quotation not found")
    if quotation.status != models.QuotationStatus.approved:
        raise HTTPException(400, "Only approved quotations can be converted to invoices")
    if quotation.invoice:
        raise HTTPException(400, f"Invoice {quotation.invoice.invoice_number} already exists for this quotation")
    invoice = _build_invoice_from_quotation(db, quotation, current_user)
    db.commit()
    db.refresh(invoice)

    if current_user.email:
        subj, html, text = tpl_invoice_created(
            invoice.invoice_number,
            quotation.quotation_number,
            quotation.customer.customer_name if quotation.customer else "",
            float(invoice.total_amount),
        )
        send_email_task.delay(current_user.email, subj, html, text)

    return invoice
