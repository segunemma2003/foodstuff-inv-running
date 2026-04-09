"""
Celery task definitions.

All tasks are imported by the worker via `include=["utils.tasks"]` in celery_app.py.
The API side only calls `.delay()` / `.apply_async()` — it never runs the body directly,
so the API response is always dispatched in < 1 ms.

Generated files (PDFs, reports) are stored in S3 under the `jobs/` prefix.
Uploaded input files are stored in S3 under the `uploads/` prefix and deleted after use.

Task categories
───────────────
  Email        → send_email_task
  PDF          → generate_quotation_pdf_task, generate_invoice_pdf_task
  Reports      → generate_report_task
  Bulk upload  → process_cost_price_bulk_task, process_product_bulk_task
"""
from celery_app import celery_app
from utils.email import send_email


# ─── Email ────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="send_email", max_retries=3, default_retry_delay=60)
def send_email_task(self, to: str, subject: str, html: str, text: str = ""):
    """Send a single email; retries up to 3 times on SMTP failure."""
    try:
        send_email(to, subject, html, text)
    except Exception as exc:
        raise self.retry(exc=exc)


# ─── PDF generation ──────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="generate_quotation_pdf")
def generate_quotation_pdf_task(self, quotation_id: int):
    from database import SessionLocal
    import models
    from utils.pdf_generator import generate_quotation_pdf
    from utils.s3 import upload_bytes

    db = SessionLocal()
    try:
        q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
        if q is None:
            raise ValueError(f"Quotation {quotation_id} not found")

        pdf_bytes = generate_quotation_pdf(q)
        s3_key = f"jobs/{self.request.id}.pdf"
        upload_bytes(s3_key, pdf_bytes, "application/pdf")
        return {
            "s3_key": s3_key,
            "filename": f"{q.quotation_number}.pdf",
            "content_type": "application/pdf",
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_invoice_pdf")
def generate_invoice_pdf_task(self, invoice_id: int):
    from database import SessionLocal
    import models
    from utils.pdf_generator import generate_invoice_pdf
    from utils.s3 import upload_bytes

    db = SessionLocal()
    try:
        inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
        if inv is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        pdf_bytes = generate_invoice_pdf(inv)
        s3_key = f"jobs/{self.request.id}.pdf"
        upload_bytes(s3_key, pdf_bytes, "application/pdf")
        return {
            "s3_key": s3_key,
            "filename": f"{inv.invoice_number}.pdf",
            "content_type": "application/pdf",
        }
    finally:
        db.close()


# ─── Report generation ───────────────────────────────────────────────────────

@celery_app.task(bind=True, name="generate_report")
def generate_report_task(self, report_type: str, params: dict):
    """
    Build an Excel report and upload it to S3.
    `params` is a plain dict with string values (JSON-safe).
    """
    from io import BytesIO
    from database import SessionLocal
    from utils.report_builder import build_report
    from utils.s3 import upload_bytes

    db = SessionLocal()
    try:
        wb, filename = build_report(report_type, params, db)
        buf = BytesIO()
        wb.save(buf)
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        s3_key = f"jobs/{self.request.id}.xlsx"
        upload_bytes(s3_key, buf.getvalue(), content_type)
        return {
            "s3_key": s3_key,
            "filename": filename,
            "content_type": content_type,
        }
    finally:
        db.close()


# ─── Send quotation to customer ──────────────────────────────────────────────

@celery_app.task(bind=True, name="send_quotation_to_customer", max_retries=3, default_retry_delay=60)
def send_quotation_to_customer_task(self, quotation_id: int):
    """Generate the quotation PDF and email it to the customer with the PDF attached."""
    from database import SessionLocal
    import models
    from utils.pdf_generator import generate_quotation_pdf
    from utils.email import send_email, tpl_quotation_to_customer

    db = SessionLocal()
    try:
        q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
        if q is None:
            raise ValueError(f"Quotation {quotation_id} not found")

        customer_email = q.customer.email if q.customer else None
        if not customer_email:
            raise ValueError(f"Customer has no email address")

        pdf_bytes = generate_quotation_pdf(q)
        subject, html, text = tpl_quotation_to_customer(
            q.quotation_number,
            q.customer.customer_name,
            float(q.total_amount),
        )
        send_email(
            to=customer_email,
            subject=subject,
            html=html,
            text=text,
            attachments=[(f"{q.quotation_number}.pdf", pdf_bytes, "application/pdf")],
        )
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


# ─── Bulk uploads ─────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="process_cost_price_bulk")
def process_cost_price_bulk_task(self, s3_key: str, user_id: int):
    """
    Download an Excel file from S3, parse cost price records, insert into DB.
    The S3 object is deleted after processing (success or failure).
    """
    from io import BytesIO
    from database import SessionLocal
    import models
    import openpyxl
    from datetime import date as date_type
    from utils.s3 import download_bytes, delete_object

    db = SessionLocal()
    try:
        raw = download_bytes(s3_key)
        wb = openpyxl.load_workbook(BytesIO(raw))
        ws = wb.active
        headers = [
            str(c.value).strip().lower() if c.value else ""
            for c in next(ws.iter_rows(min_row=1, max_row=1))
        ]
        created, errors = 0, []

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            data = dict(zip(headers, row))
            sku = data.get("sku")
            cost_price = data.get("cost_price")
            effective_date_raw = data.get("effective_date")

            if not sku or cost_price is None or not effective_date_raw:
                errors.append(f"Row {row_num}: missing required field(s)")
                continue

            product = db.query(models.Product).filter(models.Product.sku == sku).first()
            if not product:
                errors.append(f"Row {row_num}: SKU '{sku}' not found")
                continue

            if isinstance(effective_date_raw, str):
                try:
                    effective_date = date_type.fromisoformat(effective_date_raw)
                except ValueError:
                    errors.append(f"Row {row_num}: invalid date '{effective_date_raw}'")
                    continue
            else:
                effective_date = effective_date_raw  # openpyxl returns datetime/date

            db.add(models.CostPrice(
                product_id=product.id,
                cost_price=cost_price,
                effective_date=effective_date,
                notes=data.get("notes"),
                created_by=user_id,
            ))
            created += 1

        db.commit()
        return {"created": created, "errors": errors}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        delete_object(s3_key)


@celery_app.task(bind=True, name="process_product_bulk")
def process_product_bulk_task(self, s3_key: str, user_id: int):
    """Download an Excel file from S3, parse and insert product records."""
    from io import BytesIO
    from database import SessionLocal
    import models
    import openpyxl
    from utils.s3 import download_bytes, delete_object

    db = SessionLocal()
    try:
        raw = download_bytes(s3_key)
        wb = openpyxl.load_workbook(BytesIO(raw))
        ws = wb.active
        headers = [
            str(c.value).strip().lower() if c.value else ""
            for c in next(ws.iter_rows(min_row=1, max_row=1))
        ]
        created, errors = 0, []

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            data = dict(zip(headers, row))
            name = data.get("product_name")
            if not name:
                continue
            sku = data.get("sku") or None
            if sku and db.query(models.Product).filter(models.Product.sku == sku).first():
                errors.append(f"Row {row_num}: SKU '{sku}' already exists")
                continue
            category_name = data.get("category_name") or data.get("category")
            category_id = None
            if category_name:
                cat = db.query(models.ProductCategory).filter(
                    models.ProductCategory.name == category_name
                ).first()
                if cat:
                    category_id = cat.id
            db.add(models.Product(
                product_name=name,
                sku=sku,
                unit_of_measure=data.get("unit_of_measure"),
                category_id=category_id,
            ))
            created += 1

        db.commit()
        return {"created": created, "errors": errors}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        delete_object(s3_key)
