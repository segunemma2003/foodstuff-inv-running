"""Payments domain service."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit
from utils import paystack as paystack_util
from utils.email import send_email, tpl_payment_confirmed, tpl_payment_link
from utils.pdf_generator import generate_payment_receipt


def get_invoice_or_404(invoice_id: int, db: Session) -> models.Invoice:
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def recalculate_invoice_payment_status(invoice: models.Invoice, db: Session) -> None:
    total_confirmed = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.invoice_id == invoice.id,
        models.Payment.status == models.PaymentStatus.confirmed,
    ).scalar() or Decimal("0")

    invoice.amount_paid = total_confirmed
    if invoice.status in (models.InvoiceStatus.cancelled, models.InvoiceStatus.completed):
        return

    if total_confirmed >= invoice.total_amount:
        invoice.status = models.InvoiceStatus.paid
    elif total_confirmed > 0:
        invoice.status = models.InvoiceStatus.partially_paid
    else:
        invoice.status = models.InvoiceStatus.active


def balance_due(invoice: models.Invoice) -> Decimal:
    return max(Decimal("0"), invoice.total_amount - invoice.amount_paid)


def _generate_paystack_reference(invoice_number: str) -> str:
    return f"PAY-{invoice_number}-{uuid.uuid4().hex[:8].upper()}"


def list_payments(
    db: Session,
    invoice_id: Optional[int] = None,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[models.Payment]:
    payment_query = db.query(models.Payment)
    if invoice_id:
        payment_query = payment_query.filter(models.Payment.invoice_id == invoice_id)
    if status:
        payment_query = payment_query.filter(models.Payment.status == status)
    if payment_method:
        payment_query = payment_query.filter(models.Payment.payment_method == payment_method)
    return payment_query.order_by(models.Payment.created_at.desc()).offset(skip).limit(limit).all()


def bulk_delete_payments(
    db: Session,
    body: schemas.BulkIdsRequest,
    current_user: models.User,
) -> schemas.BulkDeleteResult:
    result = schemas.BulkDeleteResult()
    for pid in body.ids:
        p = db.query(models.Payment).filter(models.Payment.id == pid).first()
        if not p:
            result.failed.append({"id": pid, "detail": "Payment not found"})
            continue
        inv = p.invoice
        inv_no = inv.invoice_number if inv else ""
        audit.log(
            db,
            models.AuditAction.delete,
            models.AuditEntity.payment,
            p.id,
            current_user.id,
            description=f"Deleted payment #{p.id} ({inv_no})",
        )
        db.delete(p)
        if inv:
            recalculate_invoice_payment_status(inv, db)
        result.deleted += 1
    db.commit()
    return result


def delete_payment(db: Session, payment_id: int, current_user: models.User) -> schemas.MessageResponse:
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    inv = p.invoice
    inv_no = inv.invoice_number if inv else ""
    audit.log(
        db,
        models.AuditAction.delete,
        models.AuditEntity.payment,
        p.id,
        current_user.id,
        description=f"Deleted payment #{p.id} ({inv_no})",
    )
    db.delete(p)
    if inv:
        recalculate_invoice_payment_status(inv, db)
    db.commit()
    return schemas.MessageResponse(message="Payment deleted")


def invoice_payment_summary(db: Session, invoice_id: int) -> schemas.InvoicePaymentSummary:
    inv = get_invoice_or_404(invoice_id, db)
    payments = (
        db.query(models.Payment)
        .filter(models.Payment.invoice_id == invoice_id)
        .order_by(models.Payment.created_at.desc())
        .all()
    )
    return schemas.InvoicePaymentSummary(
        invoice_id=inv.id,
        invoice_number=inv.invoice_number,
        total_amount=inv.total_amount,
        amount_paid=inv.amount_paid,
        balance_due=balance_due(inv),
        payment_status=inv.status.value,
        payments=payments,
    )


def get_payment_receipt_stream_data(db: Session, payment_id: int) -> Tuple[BytesIO, str]:
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    if p.status != models.PaymentStatus.confirmed:
        raise HTTPException(400, "Receipt is only available for confirmed payments")
    pdf_bytes = generate_payment_receipt(p)
    filename = f"receipt-{p.invoice.invoice_number if p.invoice else payment_id}.pdf"
    return BytesIO(pdf_bytes), filename


def get_payment(db: Session, payment_id: int) -> models.Payment:
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


def record_bank_transfer(
    db: Session,
    body: schemas.BankTransferPaymentCreate,
    current_user: models.User,
) -> models.Payment:
    inv = get_invoice_or_404(body.invoice_id, db)
    if inv.status == models.InvoiceStatus.cancelled:
        raise HTTPException(400, "Cannot record payment on a cancelled invoice")
    if inv.status in (models.InvoiceStatus.paid, models.InvoiceStatus.completed):
        raise HTTPException(400, "Invoice is already fully paid")

    account = db.query(models.PaymentAccount).filter(
        models.PaymentAccount.id == body.payment_account_id,
        models.PaymentAccount.is_active,
    ).first()
    if not account:
        raise HTTPException(404, "Payment account not found or inactive")
    if body.amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero")

    payment = models.Payment(
        invoice_id=inv.id,
        amount=body.amount,
        payment_method=models.PaymentMethod.bank_transfer,
        payment_account_id=body.payment_account_id,
        payer_name=body.payer_name,
        payment_date=body.payment_date,
        notes=body.notes,
        status=models.PaymentStatus.pending,
        recorded_by=current_user.id,
    )
    db.add(payment)
    db.flush()

    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.payment,
        payment.id,
        current_user.id,
        description=(
            f"Recorded bank transfer of ₦{body.amount:,.2f} for invoice "
            f"{inv.invoice_number} — pending confirmation"
        ),
        new_values={
            "invoice_id": inv.id,
            "amount": str(body.amount),
            "payment_account_id": body.payment_account_id,
            "payment_date": str(body.payment_date),
        },
    )
    db.commit()
    db.refresh(payment)
    return payment


def confirm_payment(db: Session, payment_id: int, current_user: models.User) -> models.Payment:
    p = get_payment(db, payment_id)
    if p.status == models.PaymentStatus.confirmed:
        raise HTTPException(400, "Payment is already confirmed")
    if p.status == models.PaymentStatus.voided:
        raise HTTPException(400, "Cannot confirm a voided payment")
    if p.payment_method != models.PaymentMethod.bank_transfer:
        raise HTTPException(
            400,
            "Only bank-transfer payments can be manually confirmed. "
            "Paystack payments are confirmed automatically via webhook.",
        )

    p.status = models.PaymentStatus.confirmed
    p.confirmed_by = current_user.id
    p.confirmed_at = datetime.utcnow()
    if not p.payment_date:
        p.payment_date = date.today()

    inv = p.invoice
    recalculate_invoice_payment_status(inv, db)
    audit.log(
        db,
        models.AuditAction.confirm,
        models.AuditEntity.payment,
        p.id,
        current_user.id,
        description=f"Confirmed payment of ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
        new_values={"status": "confirmed", "invoice_status": inv.status.value},
    )
    db.commit()
    db.refresh(p)

    customer = inv.customer
    if customer and customer.email:
        subject, html, text = tpl_payment_confirmed(
            customer_name=customer.customer_name,
            invoice_number=inv.invoice_number,
            amount_paid=float(p.amount),
            balance_due=float(balance_due(inv)),
        )
        try:
            send_email(customer.email, subject, html, text)
        except Exception:
            pass
    return p


def void_payment(db: Session, payment_id: int, current_user: models.User) -> models.Payment:
    p = get_payment(db, payment_id)
    if p.status == models.PaymentStatus.voided:
        raise HTTPException(400, "Payment is already voided")

    was_confirmed = p.status == models.PaymentStatus.confirmed
    p.status = models.PaymentStatus.voided
    inv = p.invoice
    if was_confirmed:
        recalculate_invoice_payment_status(inv, db)

    audit.log(
        db,
        models.AuditAction.void,
        models.AuditEntity.payment,
        p.id,
        current_user.id,
        description=f"Voided payment of ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
        old_values={"status": "confirmed" if was_confirmed else "pending"},
        new_values={"status": "voided"},
    )
    db.commit()
    db.refresh(p)
    return p


def initialize_paystack_payment(
    db: Session,
    body: schemas.PaystackInitRequest,
    current_user: models.User,
) -> models.Payment:
    if not paystack_util.is_configured():
        raise HTTPException(
            503,
            "Paystack is not configured. Set PAYSTACK_SECRET_KEY in your environment.",
        )

    inv = get_invoice_or_404(body.invoice_id, db)
    if inv.status == models.InvoiceStatus.cancelled:
        raise HTTPException(400, "Cannot create a payment link for a cancelled invoice")
    if inv.status in (models.InvoiceStatus.paid, models.InvoiceStatus.completed):
        raise HTTPException(400, "Invoice is already fully paid")

    customer = inv.customer
    if not customer or not customer.email:
        raise HTTPException(400, "Customer must have an email address to use Paystack payment links.")

    invoice_balance = balance_due(inv)
    amount = body.amount if body.amount else invoice_balance
    if amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero")
    if amount > invoice_balance:
        raise HTTPException(
            400,
            f"Amount ₦{amount:,.2f} exceeds outstanding balance ₦{invoice_balance:,.2f}",
        )

    reference = _generate_paystack_reference(inv.invoice_number)
    try:
        ps_data = paystack_util.initialize_transaction(
            email=customer.email,
            amount_naira=amount,
            reference=reference,
            invoice_number=inv.invoice_number,
            customer_name=customer.customer_name,
        )
    except Exception as exc:
        raise HTTPException(502, f"Paystack error: {exc}")

    payment = models.Payment(
        invoice_id=inv.id,
        amount=amount,
        payment_method=models.PaymentMethod.paystack,
        paystack_reference=reference,
        paystack_access_code=ps_data.get("access_code"),
        paystack_payment_url=ps_data.get("authorization_url"),
        status=models.PaymentStatus.pending,
        recorded_by=current_user.id,
    )
    db.add(payment)
    db.flush()
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.payment,
        payment.id,
        current_user.id,
        description=(
            f"Initialized Paystack payment of ₦{amount:,.2f} for invoice "
            f"{inv.invoice_number} (ref: {reference})"
        ),
        new_values={
            "invoice_id": inv.id,
            "amount": str(amount),
            "reference": reference,
            "payment_url": ps_data.get("authorization_url"),
        },
    )
    db.commit()
    db.refresh(payment)
    return payment


def send_paystack_link_to_customer(
    db: Session,
    body: schemas.PaystackSendLinkRequest,
    current_user: models.User,
) -> models.Payment:
    p = get_payment(db, body.payment_id)
    if p.payment_method != models.PaymentMethod.paystack:
        raise HTTPException(400, "This payment is not a Paystack payment")
    if p.status != models.PaymentStatus.pending:
        raise HTTPException(400, "Can only send link for pending Paystack payments")
    if not p.paystack_payment_url:
        raise HTTPException(400, "No Paystack payment URL on this payment record")

    inv = p.invoice
    customer = inv.customer
    if not customer or not customer.email:
        raise HTTPException(400, "Customer has no email address")

    subject, html, text = tpl_payment_link(
        customer_name=customer.customer_name,
        invoice_number=inv.invoice_number,
        amount=float(p.amount),
        payment_url=p.paystack_payment_url,
    )
    try:
        send_email(customer.email, subject, html, text)
    except Exception as exc:
        raise HTTPException(502, f"Failed to send email: {exc}")

    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.payment,
        p.id,
        current_user.id,
        description=f"Sent Paystack payment link to {customer.email} for invoice {inv.invoice_number}",
    )
    db.commit()
    return p


def verify_paystack_payment(db: Session, reference: str, current_user: models.User) -> models.Payment:
    if not paystack_util.is_configured():
        raise HTTPException(503, "Paystack is not configured.")

    p = db.query(models.Payment).filter(models.Payment.paystack_reference == reference).first()
    if not p:
        raise HTTPException(404, f"No payment found with reference '{reference}'")
    try:
        ps_data = paystack_util.verify_transaction(reference)
    except Exception as exc:
        raise HTTPException(502, f"Paystack verification error: {exc}")

    if ps_data.get("status") == "success" and p.status != models.PaymentStatus.confirmed:
        p.status = models.PaymentStatus.confirmed
        p.confirmed_at = datetime.utcnow()
        if not p.payment_date:
            p.payment_date = date.today()

        inv = p.invoice
        recalculate_invoice_payment_status(inv, db)
        audit.log(
            db,
            models.AuditAction.confirm,
            models.AuditEntity.payment,
            p.id,
            current_user.id,
            description=f"Paystack payment verified: ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
            new_values={"status": "confirmed", "via": "manual_verify"},
        )
        db.commit()
        db.refresh(p)
    return p


def handle_paystack_webhook(db: Session, payload_bytes: bytes, signature: str):
    if not paystack_util.verify_webhook_signature(payload_bytes, signature):
        raise HTTPException(400, "Invalid webhook signature")
    try:
        event = json.loads(payload_bytes)
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    event_type = event.get("event")
    if event_type != "charge.success":
        return {"status": "ignored", "event": event_type}

    data = event.get("data", {})
    reference = data.get("reference")
    if not reference:
        return {"status": "no_reference"}

    p = db.query(models.Payment).filter(models.Payment.paystack_reference == reference).first()
    if not p:
        return {"status": "unknown_reference"}
    if p.status == models.PaymentStatus.confirmed:
        return {"status": "already_confirmed"}

    p.status = models.PaymentStatus.confirmed
    p.confirmed_at = datetime.utcnow()
    if not p.payment_date:
        p.payment_date = date.today()

    inv = p.invoice
    recalculate_invoice_payment_status(inv, db)
    audit.log(
        db,
        models.AuditAction.confirm,
        models.AuditEntity.payment,
        p.id,
        None,
        description=(
            f"Paystack webhook: payment ₦{p.amount:,.2f} confirmed "
            f"for invoice {inv.invoice_number} (ref: {reference})"
        ),
        new_values={"status": "confirmed", "via": "paystack_webhook"},
    )
    db.commit()

    customer = inv.customer
    if customer and customer.email:
        subject, html, text = tpl_payment_confirmed(
            customer_name=customer.customer_name,
            invoice_number=inv.invoice_number,
            amount_paid=float(p.amount),
            balance_due=float(balance_due(inv)),
        )
        try:
            send_email(customer.email, subject, html, text)
        except Exception:
            pass
    return {"status": "ok", "reference": reference}
