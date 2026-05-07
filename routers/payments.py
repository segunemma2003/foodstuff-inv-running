"""Payments router."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager, require_admin
import models
import schemas
from services import payment_service

router = APIRouter(prefix="/payments", tags=["Payments"])


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
    return payment_service.list_payments(
        db=db,
        invoice_id=invoice_id,
        status=status,
        payment_method=payment_method,
        skip=skip,
        limit=limit,
    )


@router.post("/bulk-delete", response_model=schemas.BulkDeleteResult)
def bulk_delete_payments(
    body: schemas.BulkIdsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return payment_service.bulk_delete_payments(db=db, body=body, current_user=current_user)


@router.delete("/{payment_id}", response_model=schemas.MessageResponse)
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return payment_service.delete_payment(db=db, payment_id=payment_id, current_user=current_user)


@router.get("/invoice/{invoice_id}/summary", response_model=schemas.InvoicePaymentSummary)
def invoice_payment_summary(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return payment_service.invoice_payment_summary(db=db, invoice_id=invoice_id)


@router.get("/{payment_id}/receipt")
def download_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from fastapi.responses import StreamingResponse
    payload, filename = payment_service.get_payment_receipt_stream_data(db=db, payment_id=payment_id)
    return StreamingResponse(
        payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{payment_id}", response_model=schemas.PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return payment_service.get_payment(db=db, payment_id=payment_id)


# ─── Bank Transfer payment ───────────────────────────────────────────────────

@router.post("/bank-transfer", response_model=schemas.PaymentOut, status_code=201)
def record_bank_transfer(
    body: schemas.BankTransferPaymentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return payment_service.record_bank_transfer(db=db, body=body, current_user=current_user)


# ─── Confirm / void a bank-transfer payment ──────────────────────────────────

@router.put("/{payment_id}/confirm", response_model=schemas.PaymentOut)
def confirm_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return payment_service.confirm_payment(db=db, payment_id=payment_id, current_user=current_user)


@router.put("/{payment_id}/void", response_model=schemas.PaymentOut)
def void_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return payment_service.void_payment(db=db, payment_id=payment_id, current_user=current_user)


# ─── Paystack — initialize payment link ──────────────────────────────────────

@router.post("/paystack/initialize", response_model=schemas.PaymentOut, status_code=201)
def initialize_paystack_payment(
    body: schemas.PaystackInitRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return payment_service.initialize_paystack_payment(db=db, body=body, current_user=current_user)


@router.post("/paystack/send-link", response_model=schemas.PaymentOut)
def send_paystack_link_to_customer(
    body: schemas.PaystackSendLinkRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return payment_service.send_paystack_link_to_customer(db=db, body=body, current_user=current_user)


@router.get("/paystack/verify/{reference}", response_model=schemas.PaymentOut)
def verify_paystack_payment(
    reference: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return payment_service.verify_paystack_payment(db=db, reference=reference, current_user=current_user)


# ─── Paystack Webhook ─────────────────────────────────────────────────────────

@router.post("/paystack/webhook", include_in_schema=False)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    payload_bytes = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    return payment_service.handle_paystack_webhook(db=db, payload_bytes=payload_bytes, signature=signature)
