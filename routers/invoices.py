from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager
import models
import schemas
from utils import audit
from utils.tasks import generate_invoice_pdf_task


class InvoiceSendEmailRequest(BaseModel):
    additional_emails: Optional[List[str]] = None

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get("/approved-quotations", response_model=List[schemas.QuotationOut])
def list_convertible_quotations(
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return approved quotations that have not yet been converted to invoices."""
    q = (
        db.query(models.Quotation)
        .outerjoin(models.Invoice, models.Invoice.quotation_id == models.Quotation.id)
        .filter(
            models.Quotation.status == models.QuotationStatus.approved,
            models.Invoice.id == None,
        )
    )
    if customer_id:
        q = q.filter(models.Quotation.customer_id == customer_id)
    return q.order_by(models.Quotation.approved_at.desc()).all()


@router.get("", response_model=List[schemas.InvoiceOut])
def list_invoices(
    skip: int = 0,
    limit: int = 50,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    created_by: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    payment_term: Optional[str] = None,
    delivery_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Invoice)
    if customer_id:
        q = q.filter(models.Invoice.customer_id == customer_id)
    if status:
        q = q.filter(models.Invoice.status == status)
    if created_by:
        q = q.filter(models.Invoice.created_by == created_by)
    if date_from:
        q = q.filter(models.Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(models.Invoice.invoice_date <= date_to)
    if payment_term:
        q = q.filter(models.Invoice.payment_term == payment_term)
    if delivery_type:
        q = q.filter(models.Invoice.delivery_type == delivery_type)
    return q.order_by(models.Invoice.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{invoice_id}", response_model=schemas.InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Stream invoice PDF directly (synchronous — no polling needed)."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from utils.pdf_generator import generate_invoice_pdf as gen_pdf

    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    bank_accounts = (
        db.query(models.PaymentAccount)
        .filter(models.PaymentAccount.is_active == True)
        .order_by(models.PaymentAccount.is_default.desc())
        .all()
    )

    # Find the most recent pending Paystack payment URL for this invoice
    paystack_payment = (
        db.query(models.Payment)
        .filter(
            models.Payment.invoice_id == invoice_id,
            models.Payment.paystack_payment_url.isnot(None),
            models.Payment.status == models.PaymentStatus.pending,
        )
        .order_by(models.Payment.created_at.desc())
        .first()
    )
    paystack_url = paystack_payment.paystack_payment_url if paystack_payment else None

    pdf_bytes = gen_pdf(inv, bank_accounts=bank_accounts, paystack_url=paystack_url)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{inv.invoice_number}.pdf"'},
    )


@router.post("/{invoice_id}/generate-pdf", response_model=schemas.JobEnqueuedResponse,
             status_code=202)
def generate_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """
    Queue PDF generation. Returns a task_id immediately (< 5 ms).
    Poll GET /api/v1/jobs/{task_id}, then download via GET /api/v1/jobs/{task_id}/download.
    """
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    task = generate_invoice_pdf_task.delay(invoice_id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"PDF generation queued for {inv.invoice_number}. "
                f"Poll /api/v1/jobs/{task.id} for status.",
    )


@router.post("/{invoice_id}/send-email", response_model=schemas.MessageResponse)
def send_invoice_email(
    invoice_id: int,
    body: InvoiceSendEmailRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Send invoice PDF to the customer's email and/or additional email addresses."""
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    emails: List[str] = []
    if inv.customer and inv.customer.email:
        emails.append(inv.customer.email)
    if body.additional_emails:
        emails.extend([e.strip() for e in body.additional_emails if e.strip()])

    if not emails:
        raise HTTPException(400, "No email addresses to send to")

    from io import BytesIO
    from utils.pdf_generator import generate_invoice_pdf as gen_pdf
    from utils.email import send_email, tpl_invoice_to_customer

    bank_accounts = (
        db.query(models.PaymentAccount)
        .filter(models.PaymentAccount.is_active == True)
        .order_by(models.PaymentAccount.is_default.desc())
        .all()
    )
    pdf_bytes = gen_pdf(inv, bank_accounts=bank_accounts)

    customer_name = inv.customer.customer_name if inv.customer else "Customer"
    for email in emails:
        subject, html, text = tpl_invoice_to_customer(
            invoice_number=inv.invoice_number,
            customer_name=customer_name,
            total=float(inv.total_amount),
        )
        send_email(
            to=email,
            subject=subject,
            html=html,
            text=text,
            attachments=[(f"{inv.invoice_number}.pdf", pdf_bytes, "application/pdf")],
        )

    return schemas.MessageResponse(message=f"Invoice sent to {len(emails)} recipient(s)")


@router.post("/{invoice_id}/cancel", response_model=schemas.InvoiceOut)
def cancel_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == models.InvoiceStatus.cancelled:
        raise HTTPException(400, "Invoice is already cancelled")
    inv.status = models.InvoiceStatus.cancelled
    audit.log(db, models.AuditAction.cancel, models.AuditEntity.invoice, inv.id,
               current_user.id, description=f"Cancelled invoice {inv.invoice_number}")
    db.commit()
    db.refresh(inv)
    return inv
