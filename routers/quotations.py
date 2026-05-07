from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import (
    get_current_user,
    require_not_analyst,
    require_admin_manager_or_operations,
    require_admin,
)
import models
import schemas
from services import quotations_service

router = APIRouter(prefix="/quotations", tags=["Quotations"])


class QuotationUploadToMakeRequest(BaseModel):
    additional_emails: Optional[List[str]] = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/calculate-price", response_model=List[schemas.PricePreviewResponse])
def preview_price(
    body: List[schemas.PricePreviewRequest],
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return quotations_service.preview_price(body, db)


@router.get("", response_model=List[schemas.QuotationOut])
def list_quotations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    created_by: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return quotations_service.list_quotations(
        db,
        skip=skip,
        limit=limit,
        status=status,
        customer_id=customer_id,
        created_by=created_by,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("", response_model=schemas.QuotationOut, status_code=201)
def create_quotation(
    body: schemas.QuotationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return quotations_service.create_quotation(db, body, current_user)


@router.post("/bulk-delete", response_model=schemas.BulkDeleteResult)
def bulk_delete_quotations(
    body: schemas.BulkIdsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return quotations_service.bulk_delete_quotations(db, body, current_user)


@router.delete("/{quotation_id}", response_model=schemas.MessageResponse)
def delete_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return quotations_service.delete_quotation(db, quotation_id, current_user)


@router.get("/{quotation_id}", response_model=schemas.QuotationOut)
def get_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return quotations_service.get_quotation(db, quotation_id)


@router.put("/{quotation_id}", response_model=schemas.QuotationOut)
def update_quotation(
    quotation_id: int,
    body: schemas.QuotationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return quotations_service.update_quotation(db, quotation_id, body, current_user)


@router.post("/{quotation_id}/submit", response_model=schemas.QuotationOut)
def submit_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return quotations_service.submit_quotation(db, quotation_id, current_user)


@router.post("/{quotation_id}/approve", response_model=schemas.QuotationOut)
def approve_quotation(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return quotations_service.approve_quotation(db, quotation_id, current_user)


@router.post("/{quotation_id}/reject", response_model=schemas.QuotationOut)
def reject_quotation(
    quotation_id: int,
    body: schemas.QuotationRejectRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return quotations_service.reject_quotation(db, quotation_id, body, current_user)


@router.get("/{quotation_id}/pdf")
def download_quotation_pdf(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return quotations_service.download_quotation_pdf(db, quotation_id)


@router.post("/{quotation_id}/send-to-customer", response_model=schemas.MessageResponse)
def send_quotation_to_customer(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return quotations_service.send_quotation_to_customer(db, quotation_id, current_user)


@router.post("/{quotation_id}/upload-to-make", response_model=schemas.MessageResponse)
def upload_quotation_to_make(
    quotation_id: int,
    body: QuotationUploadToMakeRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_not_analyst),
):
    return quotations_service.upload_quotation_to_make(db, quotation_id, body.additional_emails, _)


@router.post("/{quotation_id}/generate-pdf", response_model=schemas.JobEnqueuedResponse,
             status_code=202)
def generate_quotation_pdf(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return quotations_service.generate_quotation_pdf(db, quotation_id, _)


@router.post("/{quotation_id}/convert-to-invoice", response_model=schemas.InvoiceOut)
def convert_to_invoice(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return quotations_service.convert_to_invoice(db, quotation_id, current_user)
