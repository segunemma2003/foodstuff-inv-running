"""
PDF generation for quotations, invoices, and payment receipts using ReportLab.
Design matches the official Foodstuff Store document template.
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

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN       = colors.HexColor("#1e8449")
GREEN_LIGHT = colors.HexColor("#eafaf1")
WHITE       = colors.white
DARK_TEXT   = colors.HexColor("#1c1c1c")
MID_GRAY    = colors.HexColor("#888888")
BORDER_GRAY = colors.HexColor("#cccccc")

# ── Company constants ─────────────────────────────────────────────────────────
_COMPANY_NAME     = "FOODSTUFF STORE"
_COMPANY_TAGLINE  = "Eat fresh, Live healthy"
_COMPANY_SUBTITLE = "The Online Foodstuff Store"
_COMPANY_ADDR_HQ  = "The Regent Place, Beside NIPCO Filling Station, Kubwa, Abuja."
_COMPANY_ADDR_LG  = "25b, Adewale Kolawole Street, Zone 10, Lekki Phase 1, Lagos"
_COMPANY_WEB      = "www.foodstuff.store"
_COMPANY_PHONE    = "+234 906 828 0610"

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "foodstuff.png")

# ── Unicode font bootstrap ─────────────────────────────────────────────────────
_FONT       = "Helvetica"
_FONT_B     = "Helvetica-Bold"
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
            urllib.request.urlretrieve(f"{_DL_BASE}/DejaVuSans.ttf", reg_path)
        if not os.path.exists(bold_path):
            urllib.request.urlretrieve(f"{_DL_BASE}/DejaVuSans-Bold.ttf", bold_path)
        pdfmetrics.registerFont(TTFont("DejaVu",      reg_path))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
        _FONT, _FONT_B, _FONT_READY = "DejaVu", "DejaVu-Bold", True
    except Exception:
        _FONT_READY = True


def _fc(amount) -> str:
    """Currency format with Naira symbol for totals."""
    prefix = "₦" if _FONT != "Helvetica" else "NGN "
    return f"{prefix}{amount:,.2f}"


def _fmt(amount) -> str:
    """Plain number format for line-item cells."""
    return f"{float(amount):,.2f}"


def _fmt_qty(qty) -> str:
    """Format quantity — strip trailing zeros."""
    v = float(qty)
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.3f}".rstrip("0").rstrip(".")


def _fmt_date(d) -> str:
    if d is None:
        return "—"
    if hasattr(d, "date"):
        d = d.date()
    return f"{d.month}/{d.day}/{d.year}"


def _fmt_term(term: str) -> str:
    if term == "immediate":
        return "Immediate"
    return term.replace("_", " ").upper()


def _logo(target_width_cm: float = 1.6) -> Optional[RLImage]:
    if not os.path.exists(_LOGO_PATH):
        return None
    img = RLImage(_LOGO_PATH)
    iw, ih = img.imageWidth, img.imageHeight
    w = target_width_cm * cm
    h = w * ih / iw
    return RLImage(_LOGO_PATH, width=w, height=h)


def _styles():
    _ensure_unicode_font()
    s = getSampleStyleSheet()
    s["Normal"].fontName  = _FONT
    s["Normal"].fontSize  = 9
    s["Normal"].textColor = DARK_TEXT
    s["Normal"].leading   = 13

    s.add(ParagraphStyle("Right",      parent=s["Normal"], alignment=TA_RIGHT))
    s.add(ParagraphStyle("Center",     parent=s["Normal"], alignment=TA_CENTER))
    s.add(ParagraphStyle("Bold",       parent=s["Normal"], fontName=_FONT_B))
    s.add(ParagraphStyle("BoldRight",  parent=s["Normal"], fontName=_FONT_B, alignment=TA_RIGHT))
    s.add(ParagraphStyle("BoldCenter", parent=s["Normal"], fontName=_FONT_B, alignment=TA_CENTER))
    s.add(ParagraphStyle("Muted",      parent=s["Normal"], textColor=MID_GRAY, fontSize=8))
    s.add(ParagraphStyle("GreenBold",  parent=s["Normal"], fontName=_FONT_B,
                         textColor=GREEN, fontSize=10))
    s.add(ParagraphStyle("DocTitle",   parent=s["Normal"], fontName=_FONT_B, fontSize=12))
    s.add(ParagraphStyle("AddrRight",  parent=s["Normal"], fontSize=8,
                         alignment=TA_RIGHT, leading=12))
    s.add(ParagraphStyle("TableHdr",   parent=s["Normal"], fontName=_FONT_B, fontSize=9))
    s.add(ParagraphStyle("TableHdrR",  parent=s["Normal"], fontName=_FONT_B, fontSize=9,
                         alignment=TA_RIGHT))
    s.add(ParagraphStyle("White",      parent=s["Normal"], textColor=WHITE))
    s.add(ParagraphStyle("WhiteBold",  parent=s["Normal"], fontName=_FONT_B, textColor=WHITE))
    return s


# ── Shared blocks ──────────────────────────────────────────────────────────────

def _header_band(branch: str, styles) -> Table:
    """
    Two-column header:
      Left  — logo + company name + tagline + subtitle + optional branch
      Right — address block (right-aligned)
    """
    left_items = []
    logo = _logo()
    if logo:
        left_items.append(logo)
    left_items.append(Paragraph(f"<b>{_COMPANY_NAME}</b>", styles["Bold"]))
    left_items.append(Paragraph(_COMPANY_TAGLINE, styles["Muted"]))
    left_items.append(Spacer(1, 0.1 * cm))
    left_items.append(Paragraph(f"<b>{_COMPANY_SUBTITLE}</b>", styles["GreenBold"]))
    if branch:
        left_items.append(Spacer(1, 0.05 * cm))
        left_items.append(Paragraph(f"<b>{branch}</b>", styles["Bold"]))

    addr = (
        f"<b>Head Office</b>: {_COMPANY_ADDR_HQ}<br/>"
        f"<b>Lagos</b>: {_COMPANY_ADDR_LG}<br/>"
        f"<b>Web</b>: {_COMPANY_WEB}<br/>"
        f"<b>Phone</b>: {_COMPANY_PHONE}"
    )

    t = Table([[left_items, Paragraph(addr, styles["AddrRight"])]], colWidths=[9 * cm, 9 * cm])
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ALIGN",         (0, 0), (0, -1),  "LEFT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (0, -1),  0),
        ("RIGHTPADDING",  (1, 0), (1, -1),  0),
    ]))
    return t


def _customer_name_block(customer: models.Customer, styles) -> Paragraph:
    name = customer.business_name or customer.customer_name
    return Paragraph(f"<b>NAME: {name.upper()}</b>", styles["Bold"])


def _date_row(c1_lbl: str, c1_val: str,
              c2_lbl: str, c2_val: str,
              c3_lbl: str, c3_val: str,
              styles) -> Table:
    t = Table(
        [
            [Paragraph(f"<b>{c1_lbl}</b>", styles["BoldCenter"]),
             Paragraph(f"<b>{c2_lbl}</b>", styles["BoldCenter"]),
             Paragraph(f"<b>{c3_lbl}</b>", styles["BoldCenter"])],
            [Paragraph(c1_val, styles["Center"]),
             Paragraph(c2_val, styles["Center"]),
             Paragraph(c3_val, styles["Center"])],
        ],
        colWidths=[6 * cm, 6 * cm, 6 * cm],
    )
    t.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, BORDER_GRAY),
        ("LINEAFTER",     (0, 0), (1, -1),  0.5, BORDER_GRAY),
    ]))
    return t


def _items_table(items: list, styles) -> Table:
    header = [
        Paragraph("PRODUCT NAME", styles["TableHdr"]),
        Paragraph("QTY",         styles["TableHdrR"]),
        Paragraph("U.O.M",       styles["TableHdr"]),
        Paragraph("UNIT PRICE",  styles["TableHdrR"]),
        Paragraph("AMOUNT",      styles["TableHdrR"]),
    ]
    rows = [header]
    for item in items:
        name = item.product.product_name if item.product else str(item.product_id)
        uom  = getattr(item, "uom", None) or "—"
        rows.append([
            Paragraph(name,                    styles["Normal"]),
            Paragraph(_fmt_qty(item.quantity), styles["Right"]),
            Paragraph(uom,                     styles["Normal"]),
            Paragraph(_fmt(item.unit_price),   styles["Right"]),
            Paragraph(_fmt(item.line_total),   styles["Right"]),
        ])

    col_widths = [7.5 * cm, 1.5 * cm, 2 * cm, 3.5 * cm, 3.5 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("LINEABOVE",     (0, 0), (-1, 0),  1,   DARK_TEXT),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   DARK_TEXT),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.5, BORDER_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _totals_section(total_amount: Decimal, amount_paid: Decimal, styles) -> list:
    balance = max(Decimal("0"), total_amount - amount_paid)
    out = []

    # Totals aligned to AMOUNT column (starts at 14.5 cm = 7.5+1.5+2+3.5)
    _LW = 14.5 * cm   # label column width
    _VW = 3.5  * cm   # value column width — matches AMOUNT column in items table

    box_t = Table(
        [["", Paragraph(_fc(total_amount), styles["BoldRight"])]],
        colWidths=[_LW, _VW],
    )
    box_t.setStyle(TableStyle([
        ("BOX",           (1, 0), (1, 0), 0.5, BORDER_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (1, 0), (1, 0),   4),
        ("RIGHTPADDING",  (1, 0), (1, 0),   4),
    ]))
    out.append(box_t)

    # Total (VAT incl.) line
    vat_t = Table(
        [[Paragraph("Total (VAT incl.):", styles["Right"]),
          Paragraph(f"<b>{_fc(total_amount)}</b>", styles["BoldRight"])]],
        colWidths=[_LW, _VW],
    )
    vat_t.setStyle(TableStyle([
        ("LINEABOVE",     (0, 0), (-1, 0), 0.5, DARK_TEXT),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (1, 0), (1, 0),   0),
    ]))
    out.append(vat_t)

    if amount_paid > 0:
        extra_t = Table(
            [
                [Paragraph("Amount Paid:", styles["Right"]),
                 Paragraph(_fc(amount_paid), styles["Right"])],
                [Paragraph("<b>Balance Due:</b>", styles["BoldRight"]),
                 Paragraph(f"<b>{_fc(balance)}</b>", styles["BoldRight"])],
            ],
            colWidths=[_LW, _VW],
        )
        extra_t.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",  (1, 0), (1, -1),  0),
        ]))
        out.append(extra_t)

    return out


def _payment_section(payment_term: str, doc_number: str, bank_accounts: list, styles) -> list:
    out = [
        Spacer(1, 0.4 * cm),
        Paragraph(f"<b>PAYMENT TERMS:</b>          {_fmt_term(payment_term)}", styles["Normal"]),
        Spacer(1, 0.3 * cm),
        Paragraph(f"Payment Communication:    {doc_number}", styles["Normal"]),
    ]
    for i, acc in enumerate(bank_accounts):
        bank = acc.bank_name or ""
        acct = acc.account_number or ""
        name = acc.account_name or ""
        if i == 0:
            out.append(Paragraph(
                f"Account Details: <b>{acct} \u2013 {bank}</b>", styles["Normal"]
            ))
        out.append(Paragraph(f"Name:                     <b>{name}</b>", styles["Normal"]))
    return out


def _footer_line(styles) -> Table:
    t = Table(
        [[Paragraph("Thank you for your business \u2014 Foodstuff Store", styles["White"])]],
        colWidths=[18 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    return t


# ── Public generators ──────────────────────────────────────────────────────────

def generate_quotation_pdf(quotation: models.Quotation) -> bytes:
    _ensure_unicode_font()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm,  bottomMargin=1.5*cm)
    styles = _styles()
    story  = []

    story.append(_header_band("", styles))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))
    story.append(_customer_name_block(quotation.customer, styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(f"Quotation {quotation.quotation_number}", styles["DocTitle"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))

    story.append(_date_row(
        "Quotation Date", _fmt_date(quotation.quotation_date),
        "Payment Term",   _fmt_term(quotation.payment_term),
        "Delivery Type",  quotation.delivery_type.value.title(),
        styles,
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_items_table(quotation.items, styles))
    story.append(Spacer(1, 0.2 * cm))
    story += _totals_section(quotation.total_amount, Decimal("0"), styles)

    if quotation.notes:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {quotation.notes}", styles["Normal"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer_line(styles))

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

    story.append(_header_band("", styles))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))
    story.append(_customer_name_block(invoice.customer, styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(f"Invoice {invoice.invoice_number}", styles["DocTitle"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))

    story.append(_date_row(
        "Invoice Date",  _fmt_date(invoice.invoice_date),
        "Due Date",      _fmt_date(invoice.due_date),
        "Delivery Date", _fmt_date(invoice.invoice_date),
        styles,
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_items_table(invoice.items, styles))
    story.append(Spacer(1, 0.2 * cm))
    story += _totals_section(invoice.total_amount, invoice.amount_paid or Decimal("0"), styles)
    story += _payment_section(
        invoice.payment_term, invoice.invoice_number, bank_accounts or [], styles
    )

    if paystack_url:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(
            f'Pay online: <link href="{paystack_url}" color="#27ae60">{paystack_url}</link>',
            styles["Normal"],
        ))

    if invoice.notes:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", styles["Normal"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer_line(styles))

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

    story.append(_header_band("", styles))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))

    if customer:
        story.append(_customer_name_block(customer, styles))
        story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(f"Payment Receipt  RCP-{payment.id:05d}", styles["DocTitle"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceAfter=8))

    inv_num = inv.invoice_number if inv else "—"
    method  = (payment.payment_method.value if hasattr(payment.payment_method, "value")
               else str(payment.payment_method)).replace("_", " ").title()
    story.append(_date_row(
        "Receipt Date", _fmt_date(receipt_date),
        "Invoice No.",  inv_num,
        "Method",       method,
        styles,
    ))
    story.append(Spacer(1, 0.4 * cm))

    ref = payment.paystack_reference or payment.notes or "—"
    detail_rows = [
        [Paragraph("<b>Amount Received</b>", styles["Bold"]),
         Paragraph(f"<b>{_fc(payment.amount)}</b>", styles["Bold"])],
        [Paragraph("Reference", styles["Normal"]),
         Paragraph(ref,         styles["Normal"])],
    ]
    if inv:
        balance = max(Decimal("0"), inv.total_amount - (inv.amount_paid or Decimal("0")))
        detail_rows += [
            [Paragraph("Invoice Total", styles["Normal"]), Paragraph(_fc(inv.total_amount), styles["Normal"])],
            [Paragraph("Balance Due",   styles["Normal"]), Paragraph(_fc(balance),           styles["Normal"])],
        ]

    dt = Table(detail_rows, colWidths=[5 * cm, 13 * cm])
    dt.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER_GRAY),
        ("BACKGROUND",    (0, 0), (-1, 0),  GREEN_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(dt)
    story.append(Spacer(1, 0.6 * cm))

    if payment.status and payment.status.value == "confirmed":
        stamp = Table(
            [[Paragraph(
                "\u2713  PAYMENT CONFIRMED",
                ParagraphStyle("Stamp", parent=styles["BoldCenter"],
                               fontName=_FONT_B, fontSize=14, textColor=GREEN),
            )]],
            colWidths=[18 * cm],
        )
        stamp.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 2, GREEN),
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN_LIGHT),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(stamp)

    story.append(Spacer(1, 0.6 * cm))
    story.append(_footer_line(styles))

    doc.build(story)
    return buf.getvalue()
