from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
import models
import schemas
from services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview", response_model=schemas.DashboardOverview)
def overview(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return dashboard_service.get_overview(db)


# ── Cost of Sales detail ──────────────────────────────────────────────────────

class CostOfSalesEmailRequest(BaseModel):
    date_from:   Optional[date] = None
    date_to:     Optional[date] = None
    customer_id: Optional[int]  = None
    product_id:  Optional[int]  = None
    additional_emails: Optional[list[EmailStr]] = None


@router.get("/cost-of-sales")
def cost_of_sales_detail(
    date_from:   Optional[date] = None,
    date_to:     Optional[date] = None,
    customer_id: Optional[int]  = None,
    product_id:  Optional[int]  = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return dashboard_service.get_cost_of_sales_detail(
        db=db,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        product_id=product_id,
    )


@router.post("/cost-of-sales/email")
def email_cost_of_sales_report(
    body: CostOfSalesEmailRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return dashboard_service.queue_cost_of_sales_email_report(
        db=db,
        current_user=current_user,
        additional_emails=[str(e) for e in body.additional_emails] if body.additional_emails else None,
        date_from=body.date_from,
        date_to=body.date_to,
        customer_id=body.customer_id,
        product_id=body.product_id,
    )


@router.post("/cost-of-sales/upload-to-make")
def upload_cost_of_sales_to_make(
    body: CostOfSalesEmailRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Upload-to-make action for Cost of Sales.
    Uses the Cost of Sales recipient flow (primary + additional emails).
    """
    return email_cost_of_sales_report(body=body, db=db, current_user=current_user)


@router.get("/queue-events", response_model=list[schemas.QueueEventOut])
def list_queue_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return dashboard_service.list_queue_events_with_status(
        db=db,
        limit=limit,
        event_type=event_type,
    )


@router.get("/cost-of-sales/pdf")
def download_cost_of_sales_pdf(
    date_from:   Optional[date] = None,
    date_to:     Optional[date] = None,
    customer_id: Optional[int]  = None,
    product_id:  Optional[int]  = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    pdf_bytes = dashboard_service.generate_cost_of_sales_pdf_bytes(
        db=db,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        product_id=product_id,
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cost_of_sales.pdf"'},
    )
