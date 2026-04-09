from datetime import date
from sqlalchemy import extract
from sqlalchemy.orm import Session
import models


def next_quotation_number(db: Session) -> str:
    year = date.today().year
    count = (
        db.query(models.Quotation)
        .filter(extract("year", models.Quotation.created_at) == year)
        .count()
    )
    return f"QUO-{year}-{str(count + 1).zfill(4)}"


def next_invoice_number(db: Session) -> str:
    year = date.today().year
    count = (
        db.query(models.Invoice)
        .filter(extract("year", models.Invoice.created_at) == year)
        .count()
    )
    return f"INV-{year}-{str(count + 1).zfill(4)}"
