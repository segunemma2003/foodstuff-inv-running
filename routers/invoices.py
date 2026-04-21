from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager, require_not_analyst
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


@router.get("/template")
def download_invoice_template():
    """Return a sample Excel file showing the required import format."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Invoices"

    headers = [
        "invoice_number", "customer_name", "invoice_date", "due_date",
        "payment_term", "delivery_type", "product_name", "qty", "unit_price", "notes",
    ]
    header_fill = PatternFill("solid", fgColor="1e8449")
    bold_white   = Font(bold=True, color="FFFFFF")

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font   = bold_white
        cell.fill   = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = max(len(h) + 4, 16)

    sample_rows = [
        ["INV-2026-0001", "GENESIS GROUP",  "2026-01-15", "2026-02-15", "net_30",    "delivery", "Rice 50kg",   10, 85000,  ""],
        ["INV-2026-0001", "GENESIS GROUP",  "2026-01-15", "2026-02-15", "net_30",    "delivery", "Beans 50kg",   5, 45000,  ""],
        ["",              "ACME Corp",       "2026-01-16", "",           "cash",       "pickup",   "Rice 50kg",    2, 85000,  "Urgent order"],
    ]
    for r, row_data in enumerate(sample_rows, 2):
        for c, val in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=val)

    notes_ws = wb.create_sheet("Notes")
    notes_ws["A1"] = "Column Notes"
    notes_ws["A1"].font = Font(bold=True)
    notes_data = [
        ("invoice_number", "Optional. Leave blank to auto-generate. Repeat the same number across rows to group items into one invoice."),
        ("customer_name",  "Must exactly match a customer name in the system (case-insensitive)."),
        ("invoice_date",   "Required. Format: YYYY-MM-DD"),
        ("due_date",       "Optional. Format: YYYY-MM-DD"),
        ("payment_term",   "Optional. Values: cash, immediate, net_7, net_14, net_30, net_45, net_60, net_90. Default: cash"),
        ("delivery_type",  "Optional. Values: delivery, pickup. Default: pickup"),
        ("product_name",   "Must exactly match a product name in the system (case-insensitive)."),
        ("qty",            "Required. Must be > 0"),
        ("unit_price",     "Required. Selling price per unit (numbers only, no currency symbol)."),
        ("notes",          "Optional. Any notes for this invoice."),
    ]
    for i, (col, desc) in enumerate(notes_data, 2):
        notes_ws.cell(row=i, column=1, value=col).font = Font(bold=True)
        notes_ws.cell(row=i, column=2, value=desc)
    notes_ws.column_dimensions["A"].width = 18
    notes_ws.column_dimensions["B"].width = 80

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="invoice_import_template.xlsx"'},
    )


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_invoices(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_not_analyst),
):
    """
    Upload an Excel file to import invoices. Returns a task_id immediately.
    Poll GET /api/v1/jobs/{task_id} for result.
    """
    import uuid
    from utils.s3 import upload_bytes
    from utils.tasks import process_invoice_bulk_task

    content = await file.read()
    s3_key = f"uploads/invoices_{uuid.uuid4()}.xlsx"
    upload_bytes(s3_key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    task = process_invoice_bulk_task.delay(s3_key, current_user.id)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Invoice import queued. Poll /api/v1/jobs/{task.id} for result.",
    )
