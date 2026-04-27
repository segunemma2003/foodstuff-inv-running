"""
All report endpoints enqueue a Celery task and return a task_id immediately.
This ensures the API responds in < 100 ms regardless of dataset size.

Workflow
────────
  POST /api/v1/reports/{type}          → 202  {"task_id": "...", "status": "queued"}
  GET  /api/v1/jobs/{task_id}          → poll until status == "SUCCESS"
  GET  /api/v1/jobs/{task_id}/download → download the .xlsx file
"""
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
import models
import schemas
from utils.tasks import generate_report_task

router = APIRouter(prefix="/reports", tags=["Reports"])
require_report_roles = require_roles("admin", "manager", "analyst", "sales")


def _enqueue(report_type: str, params: dict) -> schemas.JobEnqueuedResponse:
    task = generate_report_task.delay(report_type, params)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Report '{report_type}' queued. "
                f"Poll /api/v1/jobs/{task.id} for status.",
    )


@router.post("/sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    customer_id: Optional[int] = None,
    payment_term: Optional[str] = None,
    delivery_type: Optional[str] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("sales", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "customer_id": customer_id,
        "payment_term": payment_term,
        "delivery_type": delivery_type,
    })


@router.post("/invoices", response_model=schemas.JobEnqueuedResponse, status_code=202)
def invoice_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("invoices", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    })


@router.post("/quotations", response_model=schemas.JobEnqueuedResponse, status_code=202)
def quotation_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("quotations", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "status": status,
    })


@router.post("/customer-sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def customer_sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("customer_sales", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    })


@router.post("/product-sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def product_sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("product_sales", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    })


@router.post("/cost-price-history", response_model=schemas.JobEnqueuedResponse, status_code=202)
def cost_price_history_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("cost_price_history", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    })


@router.post("/staff-performance", response_model=schemas.JobEnqueuedResponse, status_code=202)
def staff_performance_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return _enqueue("staff_performance", {
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
    })
