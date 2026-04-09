"""
PDF generation for quotations and invoices using ReportLab.

ReportLab's built-in fonts (Helvetica) are Latin-1 only and cannot render ₦.
We register DejaVu Sans (a free Unicode TrueType font) from the system or
download it once into /tmp on first use so the Naira sign renders correctly.
"""
import os
import urllib.request
from io import BytesIO
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import models


BRAND_COLOR = colors.HexColor("#1a5276")
LIGHT_GRAY  = colors.HexColor("#f2f3f4")

# ── Unicode font bootstrap ────────────────────────────────────────────────────

_FONT     = "Helvetica"        # updated to "DejaVu" once registered
_FONT_B   = "Helvetica-Bold"   # updated to "DejaVu-Bold" once registered
_FONT_READY = False

_SYSTEM_PATHS = [
    # Ubuntu / Heroku-22
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    # Debian
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    # macOS (local dev)
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]

_DL_CACHE = "/tmp/pdf_fonts"
_DL_BASE  = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf"


def _ensure_unicode_font():
    global _FONT, _FONT_B, _FONT_READY
    if _FONT_READY:
        return

    # 1. Try system paths
    for regular, bold in _SYSTEM_PATHS:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("DejaVu",      regular))
                pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
                _FONT, _FONT_B, _FONT_READY = "DejaVu", "DejaVu-Bold", True
                return
            except Exception:
                continue

    # 2. Download once into /tmp (dyno-local cache; re-downloaded on restart)
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
        # Last resort: keep Helvetica, replace ₦ with "NGN "
        _FONT_READY = True   # don't retry on every call


def _fc(amount) -> str:
    """Format a currency amount. Uses ₦ if a Unicode font is loaded, else NGN."""
    prefix = "₦" if _FONT != "Helvetica" else "NGN "
    return f"{prefix}{amount:,.2f}"


# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles():
    _ensure_unicode_font()
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("RightAlign", parent=s["Normal"], alignment=TA_RIGHT,
                         fontName=_FONT))
    s.add(ParagraphStyle("CenterAlign", parent=s["Normal"], alignment=TA_CENTER,
                         fontName=_FONT))
    s.add(ParagraphStyle("BoldNormal", parent=s["Normal"], fontName=_FONT_B))
    s.add(ParagraphStyle("DocTitle", parent=s["Heading1"], textColor=BRAND_COLOR,
                         fontSize=18, spaceAfter=6, fontName=_FONT_B))
    s["Normal"].fontName = _FONT
    return s


def _header_table(doc_type: str, number: str, doc_date: date, styles) -> Table:
    data = [[
        Paragraph(f"<b>FOODSTUFF STORE</b>", styles["DocTitle"]),
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
        ("BACKGROUND",   (0, 0), (-1, 0),  BRAND_COLOR),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",     (0, 0), (-1, 0),  _FONT_B),
        ("FONTNAME",     (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",     (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN",        (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _totals_table(total_amount: Decimal, styles) -> Table:
    data = [[
        "",
        Paragraph("<b>TOTAL AMOUNT</b>", styles["RightAlign"]),
        Paragraph(f"<b>{_fc(total_amount)}</b>", styles["RightAlign"]),
    ]]
    t = Table(data, colWidths=[9 * cm, 5 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("LINEABOVE", (1, 0), (-1, 0), 1, BRAND_COLOR),
        ("FONTNAME",  (1, 0), (-1, 0), _FONT_B),
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
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
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
        [f"Quotation Ref: {invoice.quotation.quotation_number}",
         "",
         f"Status: {invoice.status.value}"],
    ]
    mt = Table(meta, colWidths=[6*cm, 6*cm, 6*cm])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
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
