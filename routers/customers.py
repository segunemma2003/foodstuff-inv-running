from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends
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
def deactivate_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return customer_service.deactivate_customer(db, customer_id, current_user)


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


@router.get("/{customer_id}/cost-of-sales")
def customer_cost_of_sales(
    customer_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return customer_service.customer_cost_of_sales(db, customer_id, date_from=date_from, date_to=date_to)
