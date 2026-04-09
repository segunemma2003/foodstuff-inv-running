"""
Simple PDF generation for quotations and invoices using ReportLab.
"""
from io import BytesIO
from datetime import date
from decimal import Decimal
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

import models


BRAND_COLOR = colors.HexColor("#1a5276")
LIGHT_GRAY = colors.HexColor("#f2f3f4")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("RightAlign", parent=s["Normal"], alignment=TA_RIGHT))
    s.add(ParagraphStyle("CenterAlign", parent=s["Normal"], alignment=TA_CENTER))
    s.add(ParagraphStyle("BoldNormal", parent=s["Normal"], fontName="Helvetica-Bold"))
    s.add(ParagraphStyle(
        "DocTitle",
        parent=s["Heading1"],
        textColor=BRAND_COLOR,
        fontSize=18,
        spaceAfter=6,
    ))
    return s


def _header_table(doc_type: str, number: str, doc_date: date, styles) -> Table:
    data = [
        [
            Paragraph("<b>FOODSTUFF STORE</b>", styles["DocTitle"]),
            Paragraph(
                f"<b>{doc_type}</b><br/>{number}<br/>{doc_date.strftime('%d %b %Y')}",
                styles["RightAlign"],
            ),
        ]
    ]
    t = Table(data, colWidths=[10 * cm, 8 * cm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _customer_table(customer: models.Customer, styles) -> Table:
    name = customer.business_name or customer.customer_name
    lines = [
        f"<b>Bill To:</b> {name}",
        customer.address or "",
        customer.city or "",
        customer.phone or "",
        customer.email or "",
    ]
    body = "<br/>".join(l for l in lines if l)
    data = [[Paragraph(body, styles["Normal"])]]
    t = Table(data, colWidths=[18 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey)]))
    return t


def _items_table(items: list, styles) -> Table:
    header = [
        "Product", "Qty", "Cost Price",
        "Supply Mkp", "Del. Mkp", "PT Mkp",
        "Unit Price", "Line Total",
    ]
    rows = [header]
    for item in items:
        rows.append([
            item.product.product_name if item.product else str(item.product_id),
            f"{item.quantity:,.3f}",
            f"₦{item.cost_price:,.2f}",
            f"₦{item.supply_markup_amount:,.2f} ({item.supply_markup_pct}%)",
            f"₦{item.delivery_markup_amount:,.2f} ({item.delivery_markup_pct}%)",
            f"₦{item.payment_term_markup_amount:,.2f} ({item.payment_term_markup_pct}%)",
            f"₦{item.unit_price:,.2f}",
            f"₦{item.line_total:,.2f}",
        ])

    col_widths = [3.5 * cm, 1.5 * cm, 2 * cm, 2.5 * cm, 2 * cm, 2 * cm, 2.2 * cm, 2.3 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _totals_table(total_amount: Decimal, styles) -> Table:
    data = [
        ["", Paragraph("<b>TOTAL AMOUNT</b>", styles["RightAlign"]),
         Paragraph(f"<b>₦{total_amount:,.2f}</b>", styles["RightAlign"])],
    ]
    t = Table(data, colWidths=[9 * cm, 5 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("LINEABOVE", (1, 0), (-1, 0), 1, BRAND_COLOR),
        ("FONTNAME", (1, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    return t


def generate_quotation_pdf(quotation: models.Quotation) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = _styles()
    story = []

    story.append(_header_table("QUOTATION", quotation.quotation_number, quotation.quotation_date, styles))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_customer_table(quotation.customer, styles))
    story.append(Spacer(1, 0.3 * cm))

    meta = [
        [f"Payment Term: {quotation.payment_term}", f"Delivery: {quotation.delivery_type.value}",
         f"Status: {quotation.status.value}"],
    ]
    mt = Table(meta, colWidths=[6 * cm, 6 * cm, 6 * cm])
    mt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(mt)
    story.append(Spacer(1, 0.4 * cm))

    story.append(_items_table(quotation.items, styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_table(quotation.total_amount, styles))

    if quotation.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {quotation.notes}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def generate_invoice_pdf(invoice: models.Invoice) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = _styles()
    story = []

    story.append(_header_table("INVOICE", invoice.invoice_number, invoice.invoice_date, styles))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_customer_table(invoice.customer, styles))
    story.append(Spacer(1, 0.3 * cm))

    due_str = invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—"
    meta = [
        [f"Payment Term: {invoice.payment_term}", f"Delivery: {invoice.delivery_type.value}",
         f"Due Date: {due_str}"],
        [f"Quotation Ref: {invoice.quotation.quotation_number}", "", f"Status: {invoice.status.value}"],
    ]
    mt = Table(meta, colWidths=[6 * cm, 6 * cm, 6 * cm])
    mt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(mt)
    story.append(Spacer(1, 0.4 * cm))

    story.append(_items_table(invoice.items, styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_table(invoice.total_amount, styles))

    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
