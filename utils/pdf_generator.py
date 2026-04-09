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
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, Image as RLImage,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import models


BRAND_COLOR = colors.HexColor("#1a5276")
LIGHT_GRAY  = colors.HexColor("#f2f3f4")
GREEN       = colors.HexColor("#1e8449")
AMBER       = colors.HexColor("#d35400")

# Logo path (copied alongside this file)
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "foodstuff.png")

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
                         fontSize=16, spaceAfter=2, fontName=_FONT_B))
    s.add(ParagraphStyle("DocSubtitle", parent=s["Normal"], textColor=BRAND_COLOR,
                         fontSize=10, fontName=_FONT))
    s.add(ParagraphStyle("SmallMuted",  parent=s["Normal"], fontSize=8,
                         textColor=colors.grey, fontName=_FONT))
    s.add(ParagraphStyle("LinkStyle",   parent=s["Normal"], fontSize=9,
                         textColor=colors.HexColor("#1a5276"), fontName=_FONT))
    s["Normal"].fontName = _FONT
    return s


def _header_table(doc_type: str, number: str, doc_date: date, styles) -> Table:
    """Logo + company name on the left; document type/number/date on the right."""
    left_cells = []
    if os.path.exists(_LOGO_PATH):
        left_cells.append(RLImage(_LOGO_PATH, width=1.8 * cm, height=1.8 * cm))
    left_cells.append(Paragraph("<b>FOODSTUFF STORE</b>", styles["DocTitle"]))

    right = Paragraph(
        f"<b>{doc_type}</b><br/>{number}<br/>{doc_date.strftime('%d %b %Y')}",
        styles["RightAlign"],
    )

    data = [[left_cells, right]]
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
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _items_table(items: list, styles) -> Table:
    """Simplified 5-column table: Product | UOM | Unit Price | Qty | Sub Total."""
    header = ["Product", "UOM", "Unit Price", "Qty", "Sub Total"]
    rows = [header]
    for item in items:
        rows.append([
            item.product.product_name if item.product else str(item.product_id),
            getattr(item, "uom", None) or "—",
            _fc(item.unit_price),
            f"{item.quantity:,.3f}",
            _fc(item.line_total),
        ])

    # Full usable width = 18cm (A4 21cm - 1.5cm margins each side)
    col_widths = [7 * cm, 2 * cm, 3 * cm, 2 * cm, 4 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  BRAND_COLOR),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  _FONT_B),
        ("FONTNAME",       (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN",          (2, 0), (-1, -1), "RIGHT"),   # price/qty/total columns right-aligned
        ("ALIGN",          (1, 0), (1, -1),  "CENTER"),  # UOM centered
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
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
        ("LINEABOVE", (1, 0), (-1, 0), 1.5, BRAND_COLOR),
        ("FONTNAME",  (0, 0), (-1, -1), _FONT),
        ("FONTSIZE",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _bank_accounts_section(accounts: list, styles) -> list:
    """Return a list of flowables showing bank transfer details."""
    if not accounts:
        return []
    rows = [[
        Paragraph("<b>Bank</b>", styles["BoldNormal"]),
        Paragraph("<b>Account Number</b>", styles["BoldNormal"]),
        Paragraph("<b>Account Name</b>", styles["BoldNormal"]),
    ]]
    for acc in accounts:
        label = acc.bank_name or ""
        if acc.is_default:
            label = f"★ {label}"
        rows.append([label, acc.account_number or "", acc.account_name or ""])

    t = Table(rows, colWidths=[5 * cm, 5 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), LIGHT_GRAY),
        ("FONTNAME",    (0, 0), (-1, 0), _FONT_B),
        ("FONTNAME",    (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [t]


def _payment_options_section(bank_accounts: list, paystack_url: Optional[str],
                              styles) -> list:
    """Render a 'How to Pay' section for invoice PDFs."""
    has_bank = bool(bank_accounts)
    has_paystack = bool(paystack_url)
    if not has_bank and not has_paystack:
        return []

    flowables = [
        Spacer(1, 0.4 * cm),
        HRFlowable(width="100%", thickness=1, color=BRAND_COLOR),
        Spacer(1, 0.2 * cm),
        Paragraph("<b>How to Pay</b>", styles["BoldNormal"]),
        Spacer(1, 0.2 * cm),
    ]

    if has_paystack:
        flowables += [
            Paragraph("<b>Option 1 — Pay Online (Paystack)</b>", styles["BoldNormal"]),
            Spacer(1, 0.1 * cm),
            Paragraph(
                f'Click or visit the link below to pay securely online:<br/>'
                f'<link href="{paystack_url}" color="#1a5276">{paystack_url}</link>',
                styles["LinkStyle"],
            ),
            Spacer(1, 0.3 * cm),
        ]

    if has_bank:
        title = f"<b>Option {'2' if has_paystack else '1'} — Bank Transfer</b>"
        flowables += [
            Paragraph(title, styles["BoldNormal"]),
            Spacer(1, 0.1 * cm),
            Paragraph("Transfer payment to any of the accounts below and send your receipt to us:",
                      styles["Normal"]),
            Spacer(1, 0.15 * cm),
        ]
        flowables += _bank_accounts_section(bank_accounts, styles)

    return flowables


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


def generate_invoice_pdf(
    invoice: models.Invoice,
    bank_accounts: list = None,
    paystack_url: Optional[str] = None,
) -> bytes:
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

    # Payment options (Paystack + bank transfer)
    story += _payment_options_section(bank_accounts or [], paystack_url, styles)

    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", styles["Normal"]))

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(
        "Thank you for your business. Please keep this invoice for your records.",
        styles["SmallMuted"],
    ))

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

    # Header with logo
    header_left = []
    if os.path.exists(_LOGO_PATH):
        header_left.append(RLImage(_LOGO_PATH, width=1.8 * cm, height=1.8 * cm))
    header_left.append(Paragraph("<b>FOODSTUFF STORE</b>", styles["DocTitle"]))
    header_left.append(Paragraph("<b>PAYMENT RECEIPT</b>",
                                  ParagraphStyle("ReceiptTitle", parent=styles["Normal"],
                                                 fontName=_FONT_B, fontSize=13,
                                                 textColor=GREEN, spaceAfter=4)))

    hdr = Table([[header_left, ""]], colWidths=[14 * cm, 3 * cm])
    hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(hdr)
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
