from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager, require_not_analyst, require_admin
import models
import schemas
from services import invoice_service


class InvoiceSendEmailRequest(BaseModel):
    additional_emails: Optional[List[str]] = None

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get("/approved-quotations", response_model=List[schemas.QuotationOut])
def list_convertible_quotations(
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.list_convertible_quotations(db, customer_id)


@router.get("/template")
def download_invoice_template():
    return invoice_service.download_invoice_template()


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_invoices(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_not_analyst),
):
    return await invoice_service.bulk_upload_invoices(file, current_user)


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
    return invoice_service.list_invoices(
        db,
        skip=skip,
        limit=limit,
        customer_id=customer_id,
        status=status,
        created_by=created_by,
        date_from=date_from,
        date_to=date_to,
        payment_term=payment_term,
        delivery_type=delivery_type,
    )


@router.post("/bulk-delete", response_model=schemas.BulkDeleteResult)
def bulk_delete_invoices(
    body: schemas.BulkIdsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return invoice_service.bulk_delete_invoices(db, body, current_user)


@router.post("", response_model=schemas.InvoiceOut, status_code=201)
def create_invoice(
    body: schemas.InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return invoice_service.create_invoice(db, body, current_user)


@router.get("/{invoice_id}", response_model=schemas.InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.get_invoice(db, invoice_id)


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.download_invoice_pdf(db, invoice_id)


@router.get("/{invoice_id}/signed-pdf")
def download_signed_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.download_signed_invoice_pdf(db, invoice_id)


@router.get("/{invoice_id}/cost-of-sales/pdf")
def download_invoice_cost_of_sales_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.download_invoice_cost_of_sales_pdf(db, invoice_id)


@router.post("/{invoice_id}/upload-pdf", response_model=schemas.InvoiceOut)
async def upload_invoice_pdf(
    invoice_id: int,
    file: UploadFile = File(...),
    additional_emails: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return await invoice_service.upload_invoice_pdf(db, invoice_id, file, additional_emails, _)


@router.delete("/{invoice_id}/upload-pdf", response_model=schemas.InvoiceOut)
def remove_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.remove_invoice_pdf(db, invoice_id)


@router.post("/{invoice_id}/upload-signed", response_model=schemas.InvoiceOut)
async def upload_signed_invoice(
    invoice_id: int,
    file: UploadFile = File(...),
    additional_emails: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return await invoice_service.upload_signed_invoice(db, invoice_id, file, current_user)


@router.post("/{invoice_id}/generate-pdf", response_model=schemas.JobEnqueuedResponse,
             status_code=202)
def generate_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.generate_invoice_pdf(db, invoice_id, _)


@router.post("/{invoice_id}/send-email", response_model=schemas.MessageResponse)
def send_invoice_email(
    invoice_id: int,
    body: InvoiceSendEmailRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.send_invoice_email(db, invoice_id, body.additional_emails, _)


@router.post("/{invoice_id}/upload-to-make", response_model=schemas.MessageResponse)
def upload_invoice_to_make(
    invoice_id: int,
    body: InvoiceSendEmailRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return invoice_service.upload_invoice_to_make(db, invoice_id, body.additional_emails, _)


@router.post("/{invoice_id}/cancel", response_model=schemas.InvoiceOut)
def cancel_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return invoice_service.cancel_invoice(db, invoice_id, current_user)


@router.delete("/{invoice_id}", response_model=schemas.MessageResponse)
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return invoice_service.delete_invoice(db, invoice_id, current_user)

