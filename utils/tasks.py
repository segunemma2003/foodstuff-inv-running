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


@celery_app.task(bind=True, name="process_invoice_bulk_task")
def process_invoice_bulk_task(self, s3_key: str, user_id: int):
    """
    Parse an Excel invoice import file and create invoices + line items.

    Rows sharing the same invoice_number (or same customer_name + invoice_date
    when invoice_number is blank) are grouped into one invoice.

    Required columns : customer_name, invoice_date, product_name, qty, unit_price
    Optional columns : invoice_number, due_date, payment_term, delivery_type, notes
    """
    from io import BytesIO
    from datetime import datetime, date as date_type
    from collections import OrderedDict
    from database import SessionLocal
    import models
    import openpyxl
    from utils.s3 import download_bytes, delete_object
    from utils.number_gen import next_invoice_number

    db = SessionLocal()
    try:
        raw = download_bytes(s3_key)
        wb = openpyxl.load_workbook(BytesIO(raw), data_only=True)
        ws = wb.active
        headers = [
            str(c.value).strip().lower().replace(" ", "_") if c.value else ""
            for c in next(ws.iter_rows(min_row=1, max_row=1))
        ]

        def _parse_date(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val.date()
            if isinstance(val, date_type):
                return val
            try:
                return date_type.fromisoformat(str(val).strip())
            except ValueError:
                return None

        def _str(val, default=""):
            return str(val).strip() if val is not None else default

        groups: OrderedDict = OrderedDict()
        errors = []

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            data = dict(zip(headers, row))
            if not any(v for v in data.values()):
                continue

            customer_name = _str(data.get("customer_name"))
            invoice_date  = _parse_date(data.get("invoice_date"))
            product_name  = _str(data.get("product_name"))

            if not customer_name or not invoice_date or not product_name:
                errors.append(f"Row {row_num}: customer_name, invoice_date and product_name are required")
                continue

            try:
                qty        = float(data.get("qty") or data.get("quantity") or 0)
                unit_price = float(data.get("unit_price") or 0)
            except (ValueError, TypeError):
                errors.append(f"Row {row_num}: qty and unit_price must be numbers")
                continue

            if qty <= 0:
                errors.append(f"Row {row_num}: qty must be > 0")
                continue

            explicit_num = _str(data.get("invoice_number"))
            group_key    = explicit_num or f"{customer_name}|{invoice_date.isoformat()}"

            if group_key not in groups:
                due = _parse_date(data.get("due_date"))
                pt  = _str(data.get("payment_term"), "cash").lower().replace(" ", "_")
                dt  = _str(data.get("delivery_type"), "pickup").lower()
                groups[group_key] = {
                    "customer_name":   customer_name,
                    "invoice_date":    invoice_date,
                    "due_date":        due,
                    "payment_term":    pt,
                    "delivery_type":   dt,
                    "notes":           _str(data.get("notes")) or None,
                    "explicit_number": explicit_num or None,
                    "first_row":       row_num,
                    "items":           [],
                }

            groups[group_key]["items"].append({
                "product_name": product_name,
                "qty":          qty,
                "unit_price":   unit_price,
                "row_num":      row_num,
            })

        created = skipped = 0

        for group_key, grp in groups.items():
            customer = (
                db.query(models.Customer)
                .filter(models.Customer.customer_name.ilike(grp["customer_name"]))
                .first()
            )
            if not customer:
                errors.append(f"Row {grp['first_row']}: customer '{grp['customer_name']}' not found")
                skipped += 1
                continue

            try:
                delivery_type = models.DeliveryType(grp["delivery_type"])
            except ValueError:
                delivery_type = models.DeliveryType.pickup

            line_items = []
            invoice_total = 0.0

            for item_data in grp["items"]:
                product = (
                    db.query(models.Product)
                    .filter(models.Product.product_name.ilike(item_data["product_name"]))
                    .first()
                )
                if not product:
                    errors.append(f"Row {item_data['row_num']}: product '{item_data['product_name']}' not found")
                    continue

                latest_cost = (
                    db.query(models.CostPrice)
                    .filter(models.CostPrice.product_id == product.id)
                    .order_by(models.CostPrice.effective_date.desc())
                    .first()
                )
                cost_price    = float(latest_cost.cost_price) if latest_cost else 0.0
                line_total    = item_data["qty"] * item_data["unit_price"]
                invoice_total += line_total

                line_items.append(models.InvoiceItem(
                    product_id=product.id,
                    quantity=item_data["qty"],
                    uom=product.unit_of_measure,
                    cost_price=cost_price,
                    supply_markup_pct=0,
                    supply_markup_amount=0,
                    delivery_markup_pct=0,
                    delivery_markup_amount=0,
                    payment_term_markup_pct=0,
                    payment_term_markup_amount=0,
                    unit_price=item_data["unit_price"],
                    line_total=line_total,
                ))

            if not line_items:
                skipped += 1
                continue

            inv_number = grp["explicit_number"] or next_invoice_number(db)
            if db.query(models.Invoice).filter(models.Invoice.invoice_number == inv_number).first():
                errors.append(f"Invoice number '{inv_number}' already exists — skipped")
                skipped += 1
                continue

            db.add(models.Invoice(
                invoice_number=inv_number,
                quotation_id=None,
                customer_id=customer.id,
                invoice_date=grp["invoice_date"],
                due_date=grp["due_date"],
                payment_term=grp["payment_term"],
                delivery_type=delivery_type,
                notes=grp["notes"],
                total_amount=invoice_total,
                amount_paid=0,
                created_by=user_id,
                items=line_items,
            ))
            db.flush()
            created += 1

        db.commit()
        return {"created": created, "skipped": skipped, "errors": errors}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        delete_object(s3_key)
