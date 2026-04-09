"""
SMTP email helper.

All sending happens inside Celery workers (sync smtplib is fine there).
The send_email() function is called only from tasks, never from the
request/response path, so it never blocks the API.

If SMTP_USER / SMTP_PASSWORD are not set the call is a no-op (dev mode).
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Foodstuff Store")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@foodstuffstore.com")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


# ─── Core sender ─────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, html: str, text: str = "") -> None:
    """Send an email via SMTP. Raises on failure so Celery can retry."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL SKIP — SMTP not configured]  To={to!r}  Subject={subject!r}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
            srv.login(SMTP_USER, SMTP_PASSWORD)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASSWORD)
            srv.send_message(msg)


# ─── Email templates ─────────────────────────────────────────────────────────

def tpl_password_reset(user_name: str, token: str) -> tuple[str, str, str]:
    """Returns (subject, html, plain_text)."""
    url = f"{FRONTEND_URL}/reset-password?token={token}"
    subject = "Password Reset — Foodstuff Store"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1a5276">Password Reset Request</h2>
      <p>Hi <b>{user_name}</b>,</p>
      <p>Click the button below to reset your password. The link expires in <b>1 hour</b>.</p>
      <p style="margin:24px 0">
        <a href="{url}" style="background:#1a5276;color:#fff;padding:12px 24px;
           border-radius:4px;text-decoration:none;font-weight:bold">Reset Password</a>
      </p>
      <p>If you did not request this, you can safely ignore this email.</p>
      <hr/><p style="font-size:12px;color:#888">Foodstuff Store Internal System</p>
    </div>"""
    text = f"Hi {user_name},\n\nReset your password:\n{url}\n\nExpires in 1 hour."
    return subject, html, text


def tpl_quotation_submitted(
    quotation_number: str, customer_name: str, total: float, created_by: str
) -> tuple[str, str, str]:
    subject = f"[Action Required] Quotation {quotation_number} Pending Approval"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1a5276">Quotation Pending Your Approval</h2>
      <table style="border-collapse:collapse;width:100%">
        <tr><td style="padding:6px;font-weight:bold">Quotation</td><td>{quotation_number}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Customer</td><td>{customer_name}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Total</td><td>&#8358;{total:,.2f}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Created By</td><td>{created_by}</td></tr>
      </table>
      <p>Please log in to approve or reject.</p>
    </div>"""
    text = (
        f"Quotation {quotation_number} for {customer_name} "
        f"(₦{total:,.2f}) needs your approval.\nCreated by: {created_by}"
    )
    return subject, html, text


def tpl_quotation_approved(quotation_number: str, customer_name: str) -> tuple[str, str, str]:
    subject = f"Quotation {quotation_number} Approved ✓"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1e8449">Quotation Approved</h2>
      <p>Quotation <b>{quotation_number}</b> for <b>{customer_name}</b> has been
         <span style="color:#1e8449;font-weight:bold">approved</span>.</p>
      <p>You can now convert it to an invoice.</p>
    </div>"""
    text = f"Quotation {quotation_number} for {customer_name} has been approved."
    return subject, html, text


def tpl_quotation_rejected(
    quotation_number: str, customer_name: str, reason: str
) -> tuple[str, str, str]:
    subject = f"Quotation {quotation_number} Rejected"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#c0392b">Quotation Rejected</h2>
      <p>Quotation <b>{quotation_number}</b> for <b>{customer_name}</b> has been
         <span style="color:#c0392b;font-weight:bold">rejected</span>.</p>
      <p><b>Reason:</b> {reason}</p>
    </div>"""
    text = f"Quotation {quotation_number} for {customer_name} was rejected.\nReason: {reason}"
    return subject, html, text


def tpl_invoice_created(
    invoice_number: str, quotation_number: str, customer_name: str, total: float
) -> tuple[str, str, str]:
    subject = f"Invoice {invoice_number} Created"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1a5276">Invoice Created</h2>
      <table style="border-collapse:collapse;width:100%">
        <tr><td style="padding:6px;font-weight:bold">Invoice</td><td>{invoice_number}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Quotation Ref</td><td>{quotation_number}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Customer</td><td>{customer_name}</td></tr>
        <tr><td style="padding:6px;font-weight:bold">Total</td><td>&#8358;{total:,.2f}</td></tr>
      </table>
    </div>"""
    text = f"Invoice {invoice_number} (ref: {quotation_number}) for {customer_name} — ₦{total:,.2f}"
    return subject, html, text


def tpl_payment_link(
    customer_name: str,
    invoice_number: str,
    amount: float,
    payment_url: str,
    company_name: str = "Foodstuff Store",
) -> tuple[str, str, str]:
    """Payment link email sent to a customer so they can pay online via Paystack."""
    subject = f"Payment Request — Invoice {invoice_number}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1a5276">Payment Request from {company_name}</h2>
      <p>Dear <b>{customer_name}</b>,</p>
      <p>Please find your payment details below for invoice <b>{invoice_number}</b>.</p>
      <table style="border-collapse:collapse;width:100%;margin:16px 0">
        <tr style="background:#f2f4f6">
          <td style="padding:10px;font-weight:bold">Invoice Number</td>
          <td style="padding:10px">{invoice_number}</td>
        </tr>
        <tr>
          <td style="padding:10px;font-weight:bold">Amount Due</td>
          <td style="padding:10px;color:#c0392b;font-weight:bold">&#8358;{amount:,.2f}</td>
        </tr>
      </table>
      <p>Click the button below to pay securely online:</p>
      <p style="margin:24px 0">
        <a href="{payment_url}"
           style="background:#1a5276;color:#fff;padding:14px 28px;border-radius:4px;
                  text-decoration:none;font-weight:bold;font-size:16px">
          Pay Now &#8358;{amount:,.2f}
        </a>
      </p>
      <p style="font-size:13px;color:#666">
        This link is powered by Paystack and is secure. If you have any questions,
        please contact us.
      </p>
      <hr/>
      <p style="font-size:12px;color:#888">{company_name} — Automated Payment System</p>
    </div>"""
    text = (
        f"Dear {customer_name},\n\n"
        f"Please pay ₦{amount:,.2f} for invoice {invoice_number}.\n\n"
        f"Payment link: {payment_url}\n\n"
        f"Powered by Paystack."
    )
    return subject, html, text


def tpl_payment_confirmed(
    customer_name: str,
    invoice_number: str,
    amount_paid: float,
    balance_due: float,
    company_name: str = "Foodstuff Store",
) -> tuple[str, str, str]:
    """Payment confirmation email sent to a customer after a payment is confirmed."""
    status_text = "fully settled" if balance_due <= 0 else f"partially paid (balance: ₦{balance_due:,.2f})"
    subject = f"Payment Confirmed — Invoice {invoice_number}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px">
      <h2 style="color:#1e8449">Payment Confirmed</h2>
      <p>Dear <b>{customer_name}</b>,</p>
      <p>We have received your payment for invoice <b>{invoice_number}</b>. Thank you!</p>
      <table style="border-collapse:collapse;width:100%;margin:16px 0">
        <tr style="background:#f2f4f6">
          <td style="padding:10px;font-weight:bold">Invoice Number</td>
          <td style="padding:10px">{invoice_number}</td>
        </tr>
        <tr>
          <td style="padding:10px;font-weight:bold">Amount Received</td>
          <td style="padding:10px;color:#1e8449;font-weight:bold">&#8358;{amount_paid:,.2f}</td>
        </tr>
        <tr style="background:#f2f4f6">
          <td style="padding:10px;font-weight:bold">Balance Due</td>
          <td style="padding:10px">&#8358;{balance_due:,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px;font-weight:bold">Status</td>
          <td style="padding:10px">{status_text.capitalize()}</td>
        </tr>
      </table>
      <p>If you have any questions, please contact us.</p>
      <hr/>
      <p style="font-size:12px;color:#888">{company_name} — Automated Payment System</p>
    </div>"""
    text = (
        f"Dear {customer_name},\n\n"
        f"Payment of ₦{amount_paid:,.2f} confirmed for invoice {invoice_number}.\n"
        f"Balance due: ₦{balance_due:,.2f}\n"
        f"Status: {status_text}"
    )
    return subject, html, text
