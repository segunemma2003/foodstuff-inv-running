"""Report enqueue service."""

from typing import Optional
from datetime import date

import schemas
from services.integrations.tasks import generate_report_task


def _enqueue(report_type: str, params: dict) -> schemas.JobEnqueuedResponse:
    task = generate_report_task.delay(report_type, params)
    return schemas.JobEnqueuedResponse(
        task_id=task.id,
        message=f"Report '{report_type}' queued. Poll /api/v1/jobs/{task.id} for status.",
    )


def sales_report(
    date_from: Optional[date],
    date_to: Optional[date],
    customer_id: Optional[int],
    payment_term: Optional[str],
    delivery_type: Optional[str],
) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "sales",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
            "customer_id": customer_id,
            "payment_term": payment_term,
            "delivery_type": delivery_type,
        },
    )


def invoice_report(date_from: Optional[date], date_to: Optional[date]) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "invoices",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
        },
    )


def quotation_report(
    date_from: Optional[date], date_to: Optional[date], status: Optional[str]
) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "quotations",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
            "status": status,
        },
    )


def customer_sales_report(date_from: Optional[date], date_to: Optional[date]) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "customer_sales",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
        },
    )


def product_sales_report(date_from: Optional[date], date_to: Optional[date]) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "product_sales",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
        },
    )


def cost_price_history_report(date_from: Optional[date], date_to: Optional[date]) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "cost_price_history",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
        },
    )


def staff_performance_report(date_from: Optional[date], date_to: Optional[date]) -> schemas.JobEnqueuedResponse:
    return _enqueue(
        "staff_performance",
        {
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
        },
    )
