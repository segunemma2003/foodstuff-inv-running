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

from dependencies import require_roles
import models
import schemas
from services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])
require_report_roles = require_roles("admin", "manager", "analyst")


@router.post("/sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    customer_id: Optional[int] = None,
    payment_term: Optional[str] = None,
    delivery_type: Optional[str] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.sales_report(date_from, date_to, customer_id, payment_term, delivery_type)


@router.post("/invoices", response_model=schemas.JobEnqueuedResponse, status_code=202)
def invoice_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.invoice_report(date_from, date_to)


@router.post("/quotations", response_model=schemas.JobEnqueuedResponse, status_code=202)
def quotation_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.quotation_report(date_from, date_to, status)


@router.post("/customer-sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def customer_sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.customer_sales_report(date_from, date_to)


@router.post("/product-sales", response_model=schemas.JobEnqueuedResponse, status_code=202)
def product_sales_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.product_sales_report(date_from, date_to)


@router.post("/cost-price-history", response_model=schemas.JobEnqueuedResponse, status_code=202)
def cost_price_history_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.cost_price_history_report(date_from, date_to)


@router.post("/staff-performance", response_model=schemas.JobEnqueuedResponse, status_code=202)
def staff_performance_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    _: models.User = Depends(require_report_roles),
):
    return report_service.staff_performance_report(date_from, date_to)
