"""
PDF generation for quotations, invoices, and payment receipts using ReportLab.

ReportLab's built-in fonts (Helvetica) are Latin-1 only and cannot render ₦.
We register DejaVu Sans (a free Unicode TrueType font) from the system or
download it once into /tmp on first use so the Naira sign renders correctly.
"""
import os
import urllib.request
from io import BytesIO
from datetime import date
from decimal import Decimal
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import models


BRAND_COLOR = colors.HexColor("#1a5276")
LIGHT_GRAY  = colors.HexColor("#f2f3f4")
GREEN       = colors.HexColor("#1e8449")

# ── Unicode font bootstrap ────────────────────────────────────────────────────

_FONT     = "Helvetica"
_FONT_B   = "Helvetica-Bold"
_FONT_READY = False

_SYSTEM_PATHS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
]

_DL_CACHE = "/tmp/pdf_fonts"
_DL_BASE  = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf"


def _ensure_unicode_font():
    global _FONT, _FONT_B, _FONT_READY
    if _FONT_READY:
        return

    for regular, bold in _SYSTEM_PATHS:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("DejaVu",      regular))
                pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
                _FONT, _FONT_B, _FONT_READY = "DejaVu", "DejaVu-Bold", True
                return
            except Exception:
                continue

    os.makedirs(_DL_CACHE, exist_ok=True)
    reg_path  = os.path.join(_DL_CACHE, "DejaVuSans.ttf")
    bold_path = os.path.join(_DL_CACHE, "DejaVuSans-Bold.ttf")
    try:
        if not os.path.exists(reg_path):
            urllib.request.urlretrieve(f"{_DL_BASE}/DejaVuSans.ttf",      reg_path)
        if not os.path.exists(bold_path):
            urllib.request.urlretrieve(f"{_DL_BASE}/DejaVuSans-Bold.ttf", bold_path)
        pdfmetrics.registerFont(TTFont("DejaVu",      reg_path))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
        _FONT, _FONT_B, _FONT_READY = "DejaVu", "DejaVu-Bold", True
    except Exception:
        _FONT_READY = True   # keep Helvetica, use NGN fallback


def _fc(amount) -> str:
    prefix = "₦" if _FONT != "Helvetica" else "NGN "
    return f"{prefix}{amount:,.2f}"


# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles():
    _ensure_unicode_font()
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("RightAlign",  parent=s["Normal"], alignment=TA_RIGHT, fontName=_FONT))
    s.add(ParagraphStyle("CenterAlign", parent=s["Normal"], alignment=TA_CENTER, fontName=_FONT))
    s.add(ParagraphStyle("BoldNormal",  parent=s["Normal"], fontName=_FONT_B))
    s.add(ParagraphStyle("DocTitle",    parent=s["Heading1"], textColor=BRAND_COLOR,
                         fontSize=18, spaceAfter=6, fontName=_FONT_B))
    s.add(ParagraphStyle("SmallMuted",  parent=s["Normal"], fontSize=8,
                         textColor=colors.grey, fontName=_FONT))
    s["Normal"].fontName = _FONT
    return s


def _header_table(doc_type: str, number: str, doc_date: date, styles) -> Table:
    data = [[
        Paragraph("<b>FOODSTUFF STORE</b>", styles["DocTitle"]),
        Paragraph(
            f"<b>{doc_type}</b><br/>{number}<br/>{doc_date.strftime('%d %b %Y')}",
            styles["RightAlign"],
        ),
    ]]
    t = Table(data, colWidths=[10 * cm, 8 * cm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _customer_table(customer: models.Customer, styles) -> Table:
    name  = customer.business_name or customer.customer_name
    lines = [
        f"<b>Bill To:</b> {name}",
        customer.address or "",
        customer.city    or "",
        customer.phone   or "",
        customer.email   or "",
    ]
    body = "<br/>".join(l for l in lines if l)
    data = [[Paragraph(body, styles["Normal"])]]
    t = Table(data, colWidths=[18 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey)]))
    return t


def _items_table(items: list, styles) -> Table:
    header = [
        "Product", "Qty", "UOM", "Cost Price",
        "Supply Mkp", "Del. Mkp", "PT Mkp",
        "Unit Price", "Line Total",
    ]
    rows = [header]
    for item in items:
        rows.append([
            item.product.product_name if item.product else str(item.product_id),
            f"{item.quantity:,.3f}",
            getattr(item, "uom", None) or "—",
            _fc(item.cost_price),
            f"{_fc(item.supply_markup_amount)} ({item.supply_markup_pct}%)",
            f"{_fc(item.delivery_markup_amount)} ({item.delivery_markup_pct}%)",
            f"{_fc(item.payment_term_markup_amount)} ({item.payment_term_markup_pct}%)",
            _fc(item.unit_price),
            _fc(item.line_total),
        ])

    col_widths = [3 * cm, 1.4 * cm, 1.4 * cm, 2 * cm, 2.3 * cm, 2 * cm, 2 * cm, 2 * cm, 2 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  BRAND_COLOR),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  _FONT_B),
        ("FONTNAME",       (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN",          (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _totals_table(total_amount: Decimal, amount_paid: Decimal, styles) -> Table:
    balance = max(Decimal("0"), total_amount - amount_paid)
    rows = [
        ["", Paragraph("<b>TOTAL AMOUNT</b>", styles["RightAlign"]),
         Paragraph(f"<b>{_fc(total_amount)}</b>", styles["RightAlign"])],
    ]
    if amount_paid > 0:
        rows.append([
            "", Paragraph("Amount Paid", styles["RightAlign"]),
            Paragraph(_fc(amount_paid), styles["RightAlign"]),
        ])
        rows.append([
            "", Paragraph("<b>Balance Due</b>", styles["RightAlign"]),
            Paragraph(f"<b>{_fc(balance)}</b>", styles["RightAlign"]),
        ])
    t = Table(rows, colWidths=[9 * cm, 5 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("LINEABOVE", (1, 0), (-1, 0), 1, BRAND_COLOR),
        ("FONTNAME",  (0, 0), (-1, -1), _FONT),
    ]))
    return t


def _bank_accounts_table(accounts: list, styles) -> Table:
    """Render company bank accounts for the customer to pay into."""
    if not accounts:
        return None
    rows = [[
        Paragraph("<b>Pay Into</b>", styles["BoldNormal"]),
        Paragraph("<b>Bank</b>", styles["BoldNormal"]),
        Paragraph("<b>Account Number</b>", styles["BoldNormal"]),
        Paragraph("<b>Account Name</b>", styles["BoldNormal"]),
    ]]
    for acc in accounts:
        rows.append([
            "★" if acc.is_default else "",
            acc.bank_name or "",
            acc.account_number or "",
            acc.account_name or "",
        ])
    t = Table(rows, colWidths=[1 * cm, 5 * cm, 5 * cm, 7 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), LIGHT_GRAY),
        ("FONTNAME",    (0, 0), (-1, 0), _FONT_B),
        ("FONTNAME",    (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# ── Public generators ─────────────────────────────────────────────────────────

def generate_quotation_pdf(quotation: models.Quotation) -> bytes:
    _ensure_unicode_font()
    buf  = BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    story.append(_header_table("QUOTATION", quotation.quotation_number,
                               quotation.quotation_date, styles))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_customer_table(quotation.customer, styles))
    story.append(Spacer(1, 0.3 * cm))

    meta = [[
        f"Payment Term: {quotation.payment_term}",
        f"Delivery: {quotation.delivery_type.value}",
        f"Status: {quotation.status.value}",
    ]]
    mt = Table(meta, colWidths=[6*cm, 6*cm, 6*cm])
    mt.setStyle(TableStyle([("FONTNAME", (0,0),(-1,-1),_FONT), ("FONTSIZE",(0,0),(-1,-1),9)]))
    story.append(mt)
    story.append(Spacer(1, 0.4 * cm))

    story.append(_items_table(quotation.items, styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_table(quotation.total_amount, Decimal("0"), styles))

    if quotation.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {quotation.notes}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def generate_invoice_pdf(invoice: models.Invoice, bank_accounts: list = None) -> bytes:
    _ensure_unicode_font()
    buf  = BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    story.append(_header_table("INVOICE", invoice.invoice_number,
                               invoice.invoice_date, styles))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_customer_table(invoice.customer, styles))
    story.append(Spacer(1, 0.3 * cm))

    due_str = invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—"
    meta = [
        [f"Payment Term: {invoice.payment_term}",
         f"Delivery: {invoice.delivery_type.value}",
         f"Due Date: {due_str}"],
        [f"Quotation Ref: {invoice.quotation.quotation_number if invoice.quotation else '—'}",
         "",
         f"Status: {invoice.status.value}"],
    ]
    mt = Table(meta, colWidths=[6*cm, 6*cm, 6*cm])
    mt.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),_FONT), ("FONTSIZE",(0,0),(-1,-1),9)]))
    story.append(mt)
    story.append(Spacer(1, 0.4 * cm))

    story.append(_items_table(invoice.items, styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_table(invoice.total_amount, invoice.amount_paid or Decimal("0"), styles))

    # Bank accounts section
    if bank_accounts:
        story.append(Spacer(1, 0.5 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("<b>Payment Details</b>", styles["BoldNormal"]))
        story.append(Spacer(1, 0.2 * cm))
        tbl = _bank_accounts_table(bank_accounts, styles)
        if tbl:
            story.append(tbl)

    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def generate_payment_receipt(payment: models.Payment) -> bytes:
    """Generate a PDF receipt for a single confirmed payment."""
    _ensure_unicode_font()
    buf  = BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=2*cm,  bottomMargin=2*cm)
    styles = _styles()
    story  = []

    inv      = payment.invoice
    customer = inv.customer if inv else None
    receipt_date = payment.confirmed_at or payment.payment_date or date.today()
    if hasattr(receipt_date, "strftime"):
        date_str = receipt_date.strftime("%d %b %Y")
    else:
        date_str = str(receipt_date)

    # Header
    story.append(Paragraph("<b>FOODSTUFF STORE</b>", styles["DocTitle"]))
    story.append(Paragraph(
        "<b>PAYMENT RECEIPT</b>",
        ParagraphStyle("ReceiptTitle", parent=styles["Normal"], fontName=_FONT_B,
                       fontSize=14, textColor=GREEN, spaceAfter=4),
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Receipt details table
    def row(label, value):
        return [
            Paragraph(f"<b>{label}</b>", styles["Normal"]),
            Paragraph(str(value), styles["Normal"]),
        ]

    method = (payment.payment_method.value if hasattr(payment.payment_method, "value")
               else str(payment.payment_method)).replace("_", " ").title()
    ref = payment.paystack_reference or payment.notes or "—"

    detail_rows = [
        row("Receipt No.",      f"RCP-{payment.id:05d}"),
        row("Date",             date_str),
        row("Invoice No.",      inv.invoice_number if inv else "—"),
        row("Customer",         customer.customer_name if customer else "—"),
        row("Business",         (customer.business_name or "—") if customer else "—"),
        row("Payment Method",   method),
        row("Reference",        ref),
        row("Amount Received",  _fc(payment.amount)),
    ]
    if inv:
        balance = max(Decimal("0"), inv.total_amount - (inv.amount_paid or Decimal("0")))
        detail_rows.append(row("Invoice Total", _fc(inv.total_amount)))
        detail_rows.append(row("Balance Due",   _fc(balance)))

    dt = Table(detail_rows, colWidths=[5 * cm, 12 * cm])
    dt.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (-1, -1), _FONT),
        ("FONTSIZE",       (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
    ]))
    story.append(dt)
    story.append(Spacer(1, 0.8 * cm))

    # PAID stamp
    if payment.status and payment.status.value == "confirmed":
        stamp = Table([[Paragraph("<b>✓  PAYMENT CONFIRMED</b>",
                                   ParagraphStyle("Stamp", parent=styles["CenterAlign"],
                                                  fontName=_FONT_B, fontSize=14,
                                                  textColor=GREEN))]],
                      colWidths=[17 * cm])
        stamp.setStyle(TableStyle([
            ("BOX",        (0, 0), (-1, -1), 2, GREEN),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eafaf1")),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(stamp)

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(
        "Thank you for your payment. Please keep this receipt for your records.",
        styles["SmallMuted"],
    ))

    doc.build(story)
    return buf.getvalue()
