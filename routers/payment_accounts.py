"""
Payment Accounts router.

Manages the company's bank/payment accounts that are saved in the system
and can be offered to customers as transfer destinations.

Access:
  - List / Get : any authenticated user
  - Create / Update / Delete : admin or manager only
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin, require_admin_or_manager
import models
import schemas
from utils import audit

router = APIRouter(prefix="/payment-accounts", tags=["Payment Accounts"])


@router.get("", response_model=List[schemas.PaymentAccountOut])
def list_payment_accounts(
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """List all saved payment accounts (bank accounts).
    Pass active_only=false to include deactivated accounts."""
    payment_account_query = db.query(models.PaymentAccount)
    if active_only:
        payment_account_query = payment_account_query.filter(models.PaymentAccount.is_active == True)
    return payment_account_query.order_by(models.PaymentAccount.is_default.desc(), models.PaymentAccount.bank_name).all()


@router.post("", response_model=schemas.PaymentAccountOut, status_code=201)
def create_payment_account(
    body: schemas.PaymentAccountCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Add a new bank/payment account. If is_default=True, the previous default is cleared."""
    if body.is_default:
        # Clear existing default
        db.query(models.PaymentAccount).filter(
            models.PaymentAccount.is_default == True
        ).update({"is_default": False})

    account = models.PaymentAccount(
        account_name=body.account_name,
        bank_name=body.bank_name,
        account_number=body.account_number,
        account_type=body.account_type,
        description=body.description,
        is_default=body.is_default,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(account)
    db.flush()

    audit.log(
        db, models.AuditAction.create, models.AuditEntity.payment_account, account.id,
        current_user.id,
        description=f"Created payment account: {body.bank_name} — {body.account_number}",
        new_values=body.model_dump(),
    )
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=schemas.PaymentAccountOut)
def get_payment_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    account = db.query(models.PaymentAccount).filter(models.PaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Payment account not found")
    return account


@router.put("/{account_id}", response_model=schemas.PaymentAccountOut)
def update_payment_account(
    account_id: int,
    body: schemas.PaymentAccountUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    account = db.query(models.PaymentAccount).filter(models.PaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Payment account not found")

    old = {
        "account_name": account.account_name,
        "bank_name": account.bank_name,
        "account_number": account.account_number,
        "is_active": account.is_active,
        "is_default": account.is_default,
    }

    if body.is_default is True:
        db.query(models.PaymentAccount).filter(
            models.PaymentAccount.is_default == True,
            models.PaymentAccount.id != account_id,
        ).update({"is_default": False})

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    account.updated_by = current_user.id

    audit.log(
        db, models.AuditAction.update, models.AuditEntity.payment_account, account.id,
        current_user.id,
        description=f"Updated payment account {account_id}",
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", response_model=schemas.PaymentAccountOut)
def deactivate_payment_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Soft-delete (deactivate) a payment account."""
    account = db.query(models.PaymentAccount).filter(models.PaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Payment account not found")
    if not account.is_active:
        raise HTTPException(400, "Payment account is already inactive")

    account.is_active = False
    account.is_default = False
    account.updated_by = current_user.id

    audit.log(
        db, models.AuditAction.deactivate, models.AuditEntity.payment_account, account.id,
        current_user.id,
        description=f"Deactivated payment account: {account.bank_name} — {account.account_number}",
    )
    db.commit()
    db.refresh(account)
    return account
