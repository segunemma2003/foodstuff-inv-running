from datetime import date
from sqlalchemy import extract, func
from sqlalchemy.orm import Session
import models


def _next_seq(prefix: str, last_number: str | None) -> str:
    """Derive next sequence number from the highest existing one."""
    if last_number:
        try:
            seq = int(last_number.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    year = date.today().year
    return f"{prefix}-{year}-{str(seq).zfill(4)}"


def next_quotation_number(db: Session) -> str:
    year = date.today().year
    last = (
        db.query(models.Quotation.quotation_number)
        .filter(extract("year", models.Quotation.created_at) == year)
        .order_by(models.Quotation.id.desc())
        .limit(1)
        .scalar()
    )
    return _next_seq("QUO", last)


def next_invoice_number(db: Session) -> str:
    year = date.today().year
    last = (
        db.query(models.Invoice.invoice_number)
        .filter(extract("year", models.Invoice.created_at) == year)
        .order_by(models.Invoice.id.desc())
        .limit(1)
        .scalar()
    )
    return _next_seq("INV", last)
