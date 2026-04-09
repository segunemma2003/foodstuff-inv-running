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
from typing import Optional

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

# ── Company colours (green + red, matching the logo) ─────────────────────────
GREEN       = colors.HexColor("#1e8449")   # primary brand green
GREEN_LIGHT = colors.HexColor("#eafaf1")   # very light green tint
GREEN_MID   = colors.HexColor("#27ae60")   # slightly lighter green accent
RED         = colors.HexColor("#c0392b")   # company red
RED_LIGHT   = colors.HexColor("#fdedec")   # very light red tint
WHITE       = colors.white
LIGHT_GRAY  = colors.HexColor("#f4f6f6")
DARK_TEXT   = colors.HexColor("#1c1c1c")
CONFIRMED_GREEN = colors.HexColor("#1e8449")

# Logo path (copied alongside this file)
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "foodstuff.png")

# ── Unicode font bootstrap ─────────────────────────────────────────────────────

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
        _FONT_READY = True


def _fc(amount) -> str:
    prefix = "₦" if _FONT != "Helvetica" else "NGN "
    return f"{prefix}{amount:,.2f}"


def _logo(target_width_cm: float = 3.0) -> Optional[RLImage]:
    """Return a logo Image with correct aspect ratio, or None if not found."""
    if not os.path.exists(_LOGO_PATH):
        return None
    img = RLImage(_LOGO_PATH)
    # Preserve aspect ratio from natural image dimensions
    iw, ih = img.imageWidth, img.imageHeight
    w = target_width_cm * cm
    h = w * ih / iw
    return RLImage(_LOGO_PATH, width=w, height=h)


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles():
    _ensure_unicode_font()
    s = getSampleStyleSheet()
    s["Normal"].fontName = _FONT
    s["Normal"].fontSize = 9
    s["Normal"].textColor = DARK_TEXT

    s.add(ParagraphStyle("Right",     parent=s["Normal"], alignment=TA_RIGHT))
    s.add(ParagraphStyle("Center",    parent=s["Normal"], alignment=TA_CENTER))
    s.add(ParagraphStyle("Bold",      parent=s["Normal"], fontName=_FONT_B))
    s.add(ParagraphStyle("BoldRight", parent=s["Normal"], fontName=_FONT_B, alignment=TA_RIGHT))

    s.add(ParagraphStyle("GreenTitle", parent=s["Normal"], fontName=_FONT_B,
                         textColor=GREEN, fontSize=16))
    s.add(ParagraphStyle("GreenBold",  parent=s["Normal"], fontName=_FONT_B, textColor=GREEN))

    # White text (for coloured backgrounds)
    s.add(ParagraphStyle("WhiteNormal",    parent=s["Normal"], textColor=WHITE))
    s.add(ParagraphStyle("WhiteBold",      parent=s["Normal"], fontName=_FONT_B, textColor=WHITE))
    s.add(ParagraphStyle("WhiteBoldRight", parent=s["Normal"], fontName=_FONT_B,
                         textColor=WHITE, alignment=TA_RIGHT))
    s.add(ParagraphStyle("WhiteRight",     parent=s["Normal"], textColor=WHITE, alignment=TA_RIGHT))

    s.add(ParagraphStyle("RedBold",    parent=s["Normal"], fontName=_FONT_B,
                         textColor=RED, fontSize=13))
    s.add(ParagraphStyle("SectionHdr", parent=s["Normal"], fontName=_FONT_B,
                         textColor=WHITE, fontSize=9))
    s.add(ParagraphStyle("Muted",      parent=s["Normal"], textColor=colors.grey, fontSize=8))
    s.add(ParagraphStyle("Link",       parent=s["Normal"], textColor=GREEN_MID, fontSize=9))
    return s


# ── Shared blocks ──────────────────────────────────────────────────────────────

def _header_band(doc_type: str, number: str, doc_date: date, styles) -> Table:
    """
    White background header:
      Left  — logo (aspect-ratio correct) + green company name
      Right — red doc-type box + number + date
    """
    left = []
    logo = _logo(target_width_cm=3.0)
    if logo:
        left.append(logo)
    left.append(Paragraph("FOODSTUFF STORE", styles["GreenTitle"]))

    right = [
        Paragraph(f"<b>{doc_type}</b>", styles["RedBold"]),
        Paragraph(number, styles["Right"]),
        Paragraph(doc_date.strftime("%d %b %Y"), styles["Right"]),
    ]

    t = Table([[left, right]], colWidths=[10 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1),  8),
        ("RIGHTPADDING",  (1, 0), (1, -1),  8),
        # Green bottom border under header
        ("LINEBELOW",     (0, 0), (-1, 0),  2, GREEN),
    ]))
    return t


def _bill_to(customer: models.Customer, styles) -> Table:
    name  = customer.business_name or customer.customer_name
    lines = [f"<b>Bill To</b>", name]
    for val in [customer.address, customer.city, customer.phone, customer.email]:
        if val:
            lines.append(val)
    body = "<br/>".join(lines)

    t = Table([["", Paragraph(body, styles["Normal"])]], colWidths=[0.3 * cm, 17.7 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), GREEN),
        ("BACKGROUND",    (1, 0), (1, -1), GREEN_LIGHT),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (1, 0), (1, -1),  10),
        ("RIGHTPADDING",  (1, 0), (1, -1),  10),
    ]))
    return t


def _meta_table(rows_data: list, styles) -> Table:
    rows = [[Paragraph(cell, styles["Normal"]) for cell in row] for row in rows_data]
    t = Table(rows, colWidths=[6 * cm, 6 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GRAY),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("BOX",           (0, 0), (-1, -1), 0.5, GREEN),
        ("LINEAFTER",     (0, 0), (1, -1),  0.3, colors.grey),
    ]))
    return t


def _items_table(items: list, styles) -> Table:
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

    col_widths = [7 * cm, 2 * cm, 3 * cm, 2 * cm, 4 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  GREEN),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",       (0, 0), (-1, 0),  _FONT_B),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GREEN_LIGHT]),
        ("FONTNAME",       (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.grey),
        ("LINEBELOW",      (0, 0), (-1, 0),  1, GREEN),
        ("ALIGN",          (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN",          (1, 0), (1, -1),  "CENTER"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return t


def _totals_table(total_amount: Decimal, amount_paid: Decimal, styles) -> Table:
    balance = max(Decimal("0"), total_amount - amount_paid)

    rows = [[
        "",
        Paragraph("TOTAL AMOUNT", styles["WhiteBoldRight"]),
        Paragraph(f"<b>{_fc(total_amount)}</b>", styles["WhiteBoldRight"]),
    ]]
    style_cmds = [
        ("BACKGROUND",    (1, 0), (-1, 0), GREEN),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]

    if amount_paid > 0:
        rows += [
            ["", Paragraph("Amount Paid", styles["Right"]),
             Paragraph(_fc(amount_paid), styles["Right"])],
            ["", Paragraph("<b>Balance Due</b>", styles["BoldRight"]),
             Paragraph(f"<b>{_fc(balance)}</b>", styles["BoldRight"])],
        ]
        style_cmds += [
            ("BACKGROUND", (1, 1), (-1, 1), GREEN_LIGHT),
            ("BACKGROUND", (1, 2), (-1, 2), RED),
            ("TEXTCOLOR",  (1, 2), (-1, 2), WHITE),
            ("FONTNAME",   (1, 2), (-1, 2), _FONT_B),
        ]

    t = Table(rows, colWidths=[9 * cm, 5 * cm, 4 * cm])
    t.setStyle(TableStyle(style_cmds))
    return t


def _section_hdr(title: str, styles) -> Table:
    t = Table([[Paragraph(title, styles["SectionHdr"])]], colWidths=[18 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    return t


def _bank_table(accounts: list, styles) -> Table:
    rows = [[
        Paragraph("<b>Bank</b>", styles["Bold"]),
        Paragraph("<b>Account Number</b>", styles["Bold"]),
        Paragraph("<b>Account Name</b>", styles["Bold"]),
    ]]
    for acc in accounts:
        label = ("★ " if acc.is_default else "") + (acc.bank_name or "")
        rows.append([label, acc.account_number or "", acc.account_name or ""])

    t = Table(rows, colWidths=[5 * cm, 5 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), GREEN_LIGHT),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_B),
        ("FONTNAME",      (0, 1), (-1, -1), _FONT),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _footer(text: str, styles) -> Table:
    t = Table([[Paragraph(text, styles["WhiteNormal"])]], colWidths=[18 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    return t


def _payment_options(bank_accounts: list, paystack_url: Optional[str], styles) -> list:
    has_bank     = bool(bank_accounts)
    has_paystack = bool(paystack_url)
    if not has_bank and not has_paystack:
        return []

    out = [Spacer(1, 0.4 * cm), _section_hdr("HOW TO PAY", styles), Spacer(1, 0.2 * cm)]

    if has_paystack:
        out += [
            Paragraph("<b>Option 1 — Pay Online (Paystack)</b>", styles["Bold"]),
            Spacer(1, 0.1 * cm),
            Paragraph(
                f'Visit the secure link below to pay online:<br/>'
                f'<link href="{paystack_url}" color="#27ae60">{paystack_url}</link>',
                styles["Link"],
            ),
            Spacer(1, 0.3 * cm),
        ]

    if has_bank:
        opt = "2" if has_paystack else "1"
        out += [
            Paragraph(f"<b>Option {opt} — Bank Transfer</b>", styles["Bold"]),
            Spacer(1, 0.1 * cm),
            Paragraph("Transfer to any account below and send proof of payment to us.",
                      styles["Normal"]),
            Spacer(1, 0.15 * cm),
            _bank_table(bank_accounts, styles),
        ]

    return out


# ── Public generators ──────────────────────────────────────────────────────────

def generate_quotation_pdf(quotation: models.Quotation) -> bytes:
    _ensure_unicode_font()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    story.append(_header_band("QUOTATION", quotation.quotation_number,
                               quotation.quotation_date, styles))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_bill_to(quotation.customer, styles))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_meta_table([[
        f"Payment Term: {quotation.payment_term}",
        f"Delivery: {quotation.delivery_type.value}",
        f"Status: {quotation.status.value}",
    ]], styles))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_items_table(quotation.items, styles))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_totals_table(quotation.total_amount, Decimal("0"), styles))

    if quotation.notes:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {quotation.notes}", styles["Normal"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer("Thank you for your business — Foodstuff Store", styles))

    doc.build(story)
    return buf.getvalue()


def generate_invoice_pdf(
    invoice: models.Invoice,
    bank_accounts: list = None,
    paystack_url: Optional[str] = None,
) -> bytes:
    _ensure_unicode_font()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    story.append(_header_band("INVOICE", invoice.invoice_number,
                               invoice.invoice_date, styles))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_bill_to(invoice.customer, styles))
    story.append(Spacer(1, 0.25 * cm))

    due_str = invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—"
    story.append(_meta_table([
        [f"Payment Term: {invoice.payment_term}",
         f"Delivery: {invoice.delivery_type.value}",
         f"Due Date: {due_str}"],
        [f"Quotation Ref: {invoice.quotation.quotation_number if invoice.quotation else '—'}",
         "",
         f"Status: {invoice.status.value}"],
    ], styles))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_items_table(invoice.items, styles))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_totals_table(invoice.total_amount, invoice.amount_paid or Decimal("0"), styles))

    story += _payment_options(bank_accounts or [], paystack_url, styles)

    if invoice.notes:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", styles["Normal"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer("Thank you for your business — Foodstuff Store", styles))

    doc.build(story)
    return buf.getvalue()


def generate_payment_receipt(payment: models.Payment) -> bytes:
    _ensure_unicode_font()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    inv      = payment.invoice
    customer = inv.customer if inv else None
    receipt_date = payment.confirmed_at or payment.payment_date or date.today()
    date_str = receipt_date.strftime("%d %b %Y") if hasattr(receipt_date, "strftime") else str(receipt_date)

    # Header: logo left, title right
    left = []
    logo = _logo(target_width_cm=3.0)
    if logo:
        left.append(logo)
    left.append(Paragraph("FOODSTUFF STORE", styles["GreenTitle"]))

    right_block = [
        Paragraph("PAYMENT RECEIPT", styles["RedBold"]),
        Paragraph(date_str, styles["Right"]),
    ]
    hdr = Table([[left, right_block]], colWidths=[10 * cm, 8 * cm])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1),  8),
        ("RIGHTPADDING",  (1, 0), (1, -1),  8),
        ("LINEBELOW",     (0, 0), (-1, 0),  2, GREEN),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 0.45 * cm))

    # Details
    method = (payment.payment_method.value if hasattr(payment.payment_method, "value")
               else str(payment.payment_method)).replace("_", " ").title()
    ref = payment.paystack_reference or payment.notes or "—"

    detail_data = [
        ("Receipt No.",    f"RCP-{payment.id:05d}"),
        ("Invoice No.",    inv.invoice_number if inv else "—"),
        ("Customer",       customer.customer_name if customer else "—"),
        ("Business",       (customer.business_name or "—") if customer else "—"),
        ("Payment Method", method),
        ("Reference",      ref),
        ("Amount Received", _fc(payment.amount)),
    ]
    if inv:
        balance = max(Decimal("0"), inv.total_amount - (inv.amount_paid or Decimal("0")))
        detail_data += [
            ("Invoice Total", _fc(inv.total_amount)),
            ("Balance Due",   _fc(balance)),
        ]

    det_rows = [[Paragraph(f"<b>{r[0]}</b>", styles["Bold"]),
                 Paragraph(str(r[1]), styles["Normal"])] for r in detail_data]

    # Amount Received row (index 6) gets green highlight
    amt_idx = 6
    dt = Table(det_rows, colWidths=[5 * cm, 13 * cm])
    dt.setStyle(TableStyle([
        ("FONTSIZE",       (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, GREEN_LIGHT]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("BACKGROUND",     (0, amt_idx), (-1, amt_idx), GREEN),
        ("TEXTCOLOR",      (0, amt_idx), (-1, amt_idx), WHITE),
        ("FONTNAME",       (0, amt_idx), (-1, amt_idx), _FONT_B),
    ]))
    story.append(dt)
    story.append(Spacer(1, 0.6 * cm))

    # Confirmed stamp
    if payment.status and payment.status.value == "confirmed":
        stamp = Table(
            [[Paragraph("✓  PAYMENT CONFIRMED",
                        ParagraphStyle("Stamp", parent=styles["Center"],
                                       fontName=_FONT_B, fontSize=14, textColor=GREEN))]],
            colWidths=[18 * cm],
        )
        stamp.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 2.5, GREEN),
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN_LIGHT),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(stamp)

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer("Thank you for your payment — Foodstuff Store", styles))

    doc.build(story)
    return buf.getvalue()
