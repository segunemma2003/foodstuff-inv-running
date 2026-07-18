import csv
import io
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_customer_manage_roles, require_admin
import models
import schemas
from services import customer_service

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=List[schemas.CustomerOut])
def list_customers(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.list_customers(
        db, skip=skip, limit=limit, search=search, category=category, is_active=is_active
    )


@router.get("/dropdown", response_model=List[schemas.CustomerDropdownItem])
def list_customers_dropdown(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.list_customers_for_dropdown(db)


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(
    body: schemas.CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_customer_manage_roles),
):
    return customer_service.create_customer(db, body, current_user)


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.get_customer(db, customer_id)


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(
    customer_id: int,
    body: schemas.CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_customer_manage_roles),
):
    return customer_service.update_customer(db, customer_id, body, current_user)


@router.delete("/{customer_id}", response_model=schemas.MessageResponse)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return customer_service.delete_customer(db, customer_id, current_user)


@router.get("/{customer_id}/quotations", response_model=List[schemas.QuotationOut])
def customer_quotations(
    customer_id: int,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_quotations(db, customer_id, skip=skip, limit=limit)


@router.get("/{customer_id}/invoices", response_model=List[schemas.InvoiceOut])
def customer_invoices(
    customer_id: int,
    skip: int = 0,
    limit: int = 200,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_invoices(
        db, customer_id, skip=skip, limit=limit, date_from=date_from, date_to=date_to
    )


@router.get("/{customer_id}/analytics", response_model=schemas.CustomerDetailOut)
def customer_analytics(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_analytics(db, customer_id)


@router.get("/{customer_id}/top-products")
def customer_top_products(
    customer_id: int,
    limit: int = 10,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_top_products(
        db, customer_id, limit=limit, date_from=date_from, date_to=date_to
    )


@router.post("/bulk-update")
def bulk_update_customers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_customer_manage_roles),
):
    """
    Accept a CSV with columns matching customer fields.
    Each row is matched by: email → phone → customer_name (in that priority order).
    Only non-empty CSV cells overwrite existing values.
    Returns counts of updated / not_found / skipped rows.
    """
    UPDATABLE = {"customer_name", "business_name", "phone", "email", "address", "city", "category", "default_delivery", "default_payment_term"}

    content = file.file.read().decode("utf-8-sig")  # utf-8-sig strips BOM from Excel-exported CSVs
    reader = csv.DictReader(io.StringIO(content))

    updated = 0
    not_found = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):  # row 1 is header
        email = (row.get("email") or "").strip()
        phone = (row.get("phone") or "").strip()
        name = (row.get("customer_name") or "").strip()

        customer = None
        if email:
            customer = db.query(models.Customer).filter(
                models.Customer.email == email
            ).first()
        if not customer and phone:
            customer = db.query(models.Customer).filter(
                models.Customer.phone == phone
            ).first()
        if not customer and name:
            customer = db.query(models.Customer).filter(
                models.Customer.customer_name.ilike(name)
            ).first()

        if not customer:
            not_found += 1
            errors.append(f"Row {i}: no match for email={email!r} phone={phone!r} name={name!r}")
            continue

        changes = {}
        for col in UPDATABLE:
            val = (row.get(col) or "").strip()
            if val:
                changes[col] = val

        if not changes:
            skipped += 1
            continue

        old = {k: str(getattr(customer, k)) for k in changes}
        for field, value in changes.items():
            setattr(customer, field, value)
        from utils import audit
        audit.log(
            db,
            models.AuditAction.update,
            models.AuditEntity.customer,
            customer.id,
            current_user.id,
            old_values=old,
            new_values=changes,
            description=f"Bulk CSV update",
        )
        updated += 1

    db.commit()
    return {"updated": updated, "not_found": not_found, "skipped": skipped, "errors": errors[:20]}


@router.get("/{customer_id}/cost-of-sales")
def customer_cost_of_sales(
    customer_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_cost_of_sales(db, customer_id, date_from=date_from, date_to=date_to)
