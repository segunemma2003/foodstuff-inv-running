"""
Payment Accounts router.

Manages the company's bank/payment accounts that are saved in the system
and can be offered to customers as transfer destinations.

Access:
  - List / Get : any authenticated user
  - Create / Update / Delete : admin or manager only
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin, require_admin_or_manager
import models
import schemas
from services import payment_account_service

router = APIRouter(prefix="/payment-accounts", tags=["Payment Accounts"])


@router.get("", response_model=List[schemas.PaymentAccountOut])
def list_payment_accounts(
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """List all saved payment accounts (bank accounts).
    Pass active_only=false to include deactivated accounts."""
    return payment_account_service.list_accounts(db, active_only=active_only)


@router.post("", response_model=schemas.PaymentAccountOut, status_code=201)
def create_payment_account(
    body: schemas.PaymentAccountCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Add a new bank/payment account. If is_default=True, the previous default is cleared."""
    return payment_account_service.create_account(db, body, current_user)


@router.get("/{account_id}", response_model=schemas.PaymentAccountOut)
def get_payment_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return payment_account_service.get_account(db, account_id)


@router.put("/{account_id}", response_model=schemas.PaymentAccountOut)
def update_payment_account(
    account_id: int,
    body: schemas.PaymentAccountUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return payment_account_service.update_account(db, account_id, body, current_user)


@router.delete("/{account_id}", response_model=schemas.PaymentAccountOut)
def deactivate_payment_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Soft-delete (deactivate) a payment account."""
    return payment_account_service.deactivate_account(db, account_id, current_user)
