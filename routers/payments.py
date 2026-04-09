"""
Payments router.

Two payment channels are supported:

  1. Bank Transfer — staff manually records that a customer transferred money
     to one of the company's saved payment accounts. An admin/manager confirms
     the payment after verifying the bank alert.

  2. Paystack — staff (or the system) generates a Paystack payment link for a
     specific invoice amount. The link is optionally emailed to the customer.
     When the customer pays, Paystack fires a webhook that automatically
     confirms the payment and updates the invoice status.

Invoice payment statuses:
  active          — no payment recorded yet
  partially_paid  — some payments confirmed, balance still outstanding
  paid            — full invoice amount received
  cancelled       — invoice was cancelled (payments are blocked)
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager
import models
import schemas
from utils import audit
from utils.email import send_email, tpl_payment_link, tpl_payment_confirmed
from utils import paystack as paystack_util

router = APIRouter(prefix="/payments", tags=["Payments"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_invoice_or_404(invoice_id: int, db: Session) -> models.Invoice:
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def _recalculate_invoice_payment_status(invoice: models.Invoice, db: Session) -> None:
    """
    Recompute invoice.amount_paid from confirmed payments and update its status.
    Does NOT commit — caller is responsible.
    """
    total_confirmed = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.invoice_id == invoice.id,
        models.Payment.status == models.PaymentStatus.confirmed,
    ).scalar() or Decimal("0")

    invoice.amount_paid = total_confirmed

    if invoice.status == models.InvoiceStatus.cancelled:
        return  # Never auto-change a cancelled invoice's status

    if total_confirmed >= invoice.total_amount:
        invoice.status = models.InvoiceStatus.paid
    elif total_confirmed > 0:
        invoice.status = models.InvoiceStatus.partially_paid
    else:
        invoice.status = models.InvoiceStatus.active


def _balance_due(invoice: models.Invoice) -> Decimal:
    return max(Decimal("0"), invoice.total_amount - invoice.amount_paid)


def _generate_paystack_reference(invoice_number: str) -> str:
    return f"PAY-{invoice_number}-{uuid.uuid4().hex[:8].upper()}"


# ─── List / detail ────────────────────────────────────────────────────────────

@router.get("", response_model=List[schemas.PaymentOut])
def list_payments(
    invoice_id: Optional[int] = None,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """List payment records with optional filters."""
    q = db.query(models.Payment)
    if invoice_id:
        q = q.filter(models.Payment.invoice_id == invoice_id)
    if status:
        q = q.filter(models.Payment.status == status)
    if payment_method:
        q = q.filter(models.Payment.payment_method == payment_method)
    return q.order_by(models.Payment.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/invoice/{invoice_id}/summary", response_model=schemas.InvoicePaymentSummary)
def invoice_payment_summary(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return the full payment summary (total, paid, balance) for an invoice."""
    inv = _get_invoice_or_404(invoice_id, db)
    payments = (
        db.query(models.Payment)
        .filter(models.Payment.invoice_id == invoice_id)
        .order_by(models.Payment.created_at.desc())
        .all()
    )
    balance = _balance_due(inv)
    return schemas.InvoicePaymentSummary(
        invoice_id=inv.id,
        invoice_number=inv.invoice_number,
        total_amount=inv.total_amount,
        amount_paid=inv.amount_paid,
        balance_due=balance,
        payment_status=inv.status.value,
        payments=payments,
    )


@router.get("/{payment_id}/receipt")
def download_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Stream a PDF payment receipt for a confirmed payment."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from utils.pdf_generator import generate_payment_receipt

    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    if p.status != models.PaymentStatus.confirmed:
        raise HTTPException(400, "Receipt is only available for confirmed payments")

    pdf_bytes = generate_payment_receipt(p)
    filename = f"receipt-{p.invoice.invoice_number if p.invoice else payment_id}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{payment_id}", response_model=schemas.PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


# ─── Bank Transfer payment ───────────────────────────────────────────────────

@router.post("/bank-transfer", response_model=schemas.PaymentOut, status_code=201)
def record_bank_transfer(
    body: schemas.BankTransferPaymentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Record a customer's bank transfer against an invoice.

    The payment is created with status=pending. An admin/manager must confirm it
    (via PUT /payments/{id}/confirm) after verifying the bank alert.

    The payment_account_id must be one of the company's saved payment accounts
    (GET /payment-accounts).
    """
    inv = _get_invoice_or_404(body.invoice_id, db)

    if inv.status == models.InvoiceStatus.cancelled:
        raise HTTPException(400, "Cannot record payment on a cancelled invoice")
    if inv.status == models.InvoiceStatus.paid:
        raise HTTPException(400, "Invoice is already fully paid")

    # Validate payment account
    account = db.query(models.PaymentAccount).filter(
        models.PaymentAccount.id == body.payment_account_id,
        models.PaymentAccount.is_active == True,
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
        db, models.AuditAction.create, models.AuditEntity.payment, payment.id,
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


# ─── Confirm / void a bank-transfer payment ──────────────────────────────────

@router.put("/{payment_id}/confirm", response_model=schemas.PaymentOut)
def confirm_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Confirm a pending bank-transfer payment.

    Requires admin or manager role. Once confirmed:
      - Payment status → confirmed
      - Invoice amount_paid is recalculated
      - Invoice status is updated to partially_paid or paid as appropriate
      - A payment-confirmed email is sent to the customer if they have an email on file
    """
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    if p.status == models.PaymentStatus.confirmed:
        raise HTTPException(400, "Payment is already confirmed")
    if p.status == models.PaymentStatus.voided:
        raise HTTPException(400, "Cannot confirm a voided payment")
    if p.payment_method != models.PaymentMethod.bank_transfer:
        raise HTTPException(400, "Only bank-transfer payments can be manually confirmed. "
                                 "Paystack payments are confirmed automatically via webhook.")

    p.status = models.PaymentStatus.confirmed
    p.confirmed_by = current_user.id
    p.confirmed_at = datetime.utcnow()
    if not p.payment_date:
        p.payment_date = date.today()

    inv = p.invoice
    _recalculate_invoice_payment_status(inv, db)

    audit.log(
        db, models.AuditAction.confirm, models.AuditEntity.payment, p.id,
        current_user.id,
        description=f"Confirmed payment of ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
        new_values={"status": "confirmed", "invoice_status": inv.status.value},
    )
    db.commit()
    db.refresh(p)

    # Send confirmation email to customer if email is available
    customer = inv.customer
    if customer and customer.email:
        balance = float(_balance_due(inv))
        subject, html, text = tpl_payment_confirmed(
            customer_name=customer.customer_name,
            invoice_number=inv.invoice_number,
            amount_paid=float(p.amount),
            balance_due=balance,
        )
        try:
            send_email(customer.email, subject, html, text)
        except Exception:
            pass  # Don't fail the API call if email fails

    return p


@router.put("/{payment_id}/void", response_model=schemas.PaymentOut)
def void_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Void (cancel) a pending or confirmed payment.

    Requires admin or manager role. Invoice payment status is recalculated after voiding.
    """
    p = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    if p.status == models.PaymentStatus.voided:
        raise HTTPException(400, "Payment is already voided")

    was_confirmed = p.status == models.PaymentStatus.confirmed
    p.status = models.PaymentStatus.voided

    inv = p.invoice
    if was_confirmed:
        _recalculate_invoice_payment_status(inv, db)

    audit.log(
        db, models.AuditAction.void, models.AuditEntity.payment, p.id,
        current_user.id,
        description=f"Voided payment of ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
        old_values={"status": "confirmed" if was_confirmed else "pending"},
        new_values={"status": "voided"},
    )
    db.commit()
    db.refresh(p)
    return p


# ─── Paystack — initialize payment link ──────────────────────────────────────

@router.post("/paystack/initialize", response_model=schemas.PaymentOut, status_code=201)
def initialize_paystack_payment(
    body: schemas.PaystackInitRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Generate a Paystack payment link for an invoice.

    - If `amount` is omitted, defaults to the invoice's outstanding balance.
    - The returned `paystack_payment_url` can be shared with the customer directly,
      or use POST /payments/paystack/send-link to email it automatically.
    - Payment status starts as pending; it is confirmed automatically when
      Paystack fires the charge.success webhook.
    """
    if not paystack_util.is_configured():
        raise HTTPException(
            503,
            "Paystack is not configured. Set PAYSTACK_SECRET_KEY in your environment."
        )

    inv = _get_invoice_or_404(body.invoice_id, db)

    if inv.status == models.InvoiceStatus.cancelled:
        raise HTTPException(400, "Cannot create a payment link for a cancelled invoice")
    if inv.status == models.InvoiceStatus.paid:
        raise HTTPException(400, "Invoice is already fully paid")

    customer = inv.customer
    if not customer or not customer.email:
        raise HTTPException(
            400,
            "Customer must have an email address to use Paystack payment links."
        )

    # Determine amount
    balance = _balance_due(inv)
    amount = body.amount if body.amount else balance
    if amount <= 0:
        raise HTTPException(400, "Payment amount must be greater than zero")
    if amount > balance:
        raise HTTPException(
            400,
            f"Amount ₦{amount:,.2f} exceeds outstanding balance ₦{balance:,.2f}"
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
        db, models.AuditAction.create, models.AuditEntity.payment, payment.id,
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


@router.post("/paystack/send-link", response_model=schemas.PaymentOut)
def send_paystack_link_to_customer(
    body: schemas.PaystackSendLinkRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Email the Paystack payment link to the customer for a pending Paystack payment.

    The payment must have been initialised first via POST /payments/paystack/initialize.
    """
    p = db.query(models.Payment).filter(models.Payment.id == body.payment_id).first()
    if not p:
        raise HTTPException(404, "Payment not found")
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
        db, models.AuditAction.update, models.AuditEntity.payment, p.id,
        current_user.id,
        description=(
            f"Sent Paystack payment link to {customer.email} "
            f"for invoice {inv.invoice_number}"
        ),
    )
    db.commit()
    return p


@router.get("/paystack/verify/{reference}", response_model=schemas.PaymentOut)
def verify_paystack_payment(
    reference: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Manually verify a Paystack payment by reference.

    Useful when the webhook was missed or you want to force a status check.
    Calls the Paystack API and updates the payment + invoice status if successful.
    """
    if not paystack_util.is_configured():
        raise HTTPException(503, "Paystack is not configured.")

    p = db.query(models.Payment).filter(
        models.Payment.paystack_reference == reference
    ).first()
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
        _recalculate_invoice_payment_status(inv, db)

        audit.log(
            db, models.AuditAction.confirm, models.AuditEntity.payment, p.id,
            current_user.id,
            description=f"Paystack payment verified: ₦{p.amount:,.2f} for invoice {inv.invoice_number}",
            new_values={"status": "confirmed", "via": "manual_verify"},
        )
        db.commit()
        db.refresh(p)

    return p


# ─── Paystack Webhook ─────────────────────────────────────────────────────────

@router.post("/paystack/webhook", include_in_schema=False)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Paystack webhook endpoint.

    Configure this URL in your Paystack dashboard:
      https://yourdomain.com/api/v1/payments/paystack/webhook

    Handles: charge.success
    No authentication required — Paystack signs requests with HMAC-SHA512.
    """
    payload_bytes = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not paystack_util.verify_webhook_signature(payload_bytes, signature):
        raise HTTPException(400, "Invalid webhook signature")

    import json
    try:
        event = json.loads(payload_bytes)
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    event_type = event.get("event")
    if event_type != "charge.success":
        # We only handle successful charge events; acknowledge others
        return {"status": "ignored", "event": event_type}

    data = event.get("data", {})
    reference = data.get("reference")
    if not reference:
        return {"status": "no_reference"}

    p = db.query(models.Payment).filter(
        models.Payment.paystack_reference == reference
    ).first()
    if not p:
        # Unknown reference — could be from another service, just acknowledge
        return {"status": "unknown_reference"}

    if p.status == models.PaymentStatus.confirmed:
        return {"status": "already_confirmed"}

    p.status = models.PaymentStatus.confirmed
    p.confirmed_at = datetime.utcnow()
    if not p.payment_date:
        p.payment_date = date.today()

    inv = p.invoice
    _recalculate_invoice_payment_status(inv, db)

    audit.log(
        db, models.AuditAction.confirm, models.AuditEntity.payment, p.id,
        None,  # no user — triggered by Paystack
        description=(
            f"Paystack webhook: payment ₦{p.amount:,.2f} confirmed "
            f"for invoice {inv.invoice_number} (ref: {reference})"
        ),
        new_values={"status": "confirmed", "via": "paystack_webhook"},
    )
    db.commit()

    # Send confirmation email to customer
    customer = inv.customer
    if customer and customer.email:
        balance = float(_balance_due(inv))
        subject, html, text = tpl_payment_confirmed(
            customer_name=customer.customer_name,
            invoice_number=inv.invoice_number,
            amount_paid=float(p.amount),
            balance_due=balance,
        )
        try:
            send_email(customer.email, subject, html, text)
        except Exception:
            pass

    return {"status": "ok", "reference": reference}
