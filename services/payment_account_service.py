"""Payment accounts domain."""

from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit


def list_accounts(db: Session, active_only: bool = True) -> List[models.PaymentAccount]:
    payment_account_query = db.query(models.PaymentAccount)
    if active_only:
        payment_account_query = payment_account_query.filter(models.PaymentAccount.is_active == True)
    return payment_account_query.order_by(
        models.PaymentAccount.is_default.desc(), models.PaymentAccount.bank_name
    ).all()


def create_account(db: Session, body: schemas.PaymentAccountCreate, current_user: models.User) -> models.PaymentAccount:
    if body.is_default:
        db.query(models.PaymentAccount).filter(models.PaymentAccount.is_default == True).update({"is_default": False})

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
        db,
        models.AuditAction.create,
        models.AuditEntity.payment_account,
        account.id,
        current_user.id,
        description=f"Created payment account: {body.bank_name} — {body.account_number}",
        new_values=body.model_dump(),
    )
    db.commit()
    db.refresh(account)
    return account


def get_account(db: Session, account_id: int) -> models.PaymentAccount:
    account = db.query(models.PaymentAccount).filter(models.PaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Payment account not found")
    return account


def update_account(
    db: Session, account_id: int, body: schemas.PaymentAccountUpdate, current_user: models.User
) -> models.PaymentAccount:
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
        db,
        models.AuditAction.update,
        models.AuditEntity.payment_account,
        account.id,
        current_user.id,
        description=f"Updated payment account {account_id}",
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(account)
    return account


def deactivate_account(db: Session, account_id: int, current_user: models.User) -> models.PaymentAccount:
    account = db.query(models.PaymentAccount).filter(models.PaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Payment account not found")
    if not account.is_active:
        raise HTTPException(400, "Payment account is already inactive")

    account.is_active = False
    account.is_default = False
    account.updated_by = current_user.id

    audit.log(
        db,
        models.AuditAction.deactivate,
        models.AuditEntity.payment_account,
        account.id,
        current_user.id,
        description=f"Deactivated payment account: {account.bank_name} — {account.account_number}",
    )
    db.commit()
    db.refresh(account)
    return account
