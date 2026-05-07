"""Background task dispatch — thin facade over utils.tasks."""

from utils.tasks import (
    process_cost_price_bulk_task,
    send_email_task,
    send_email_with_attachment_task,
    generate_report_task,
    generate_quotation_pdf_task,
    generate_invoice_pdf_task,
    send_invoice_to_recipients_task,
    send_quotation_to_customer_task,
    process_product_bulk_task,
    process_invoice_bulk_task,
)

__all__ = [
    "process_cost_price_bulk_task",
    "send_email_task",
    "send_email_with_attachment_task",
    "generate_report_task",
    "generate_quotation_pdf_task",
    "generate_invoice_pdf_task",
    "send_invoice_to_recipients_task",
    "send_quotation_to_customer_task",
    "process_product_bulk_task",
    "process_invoice_bulk_task",
]
