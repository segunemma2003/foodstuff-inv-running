"""Application settings."""

from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit
from utils.email import send_email, SMTP_HOST, SMTP_USER


def send_test_email(to: str, current_user: models.User) -> dict:
    if not SMTP_USER:
        raise HTTPException(503, "SMTP is not configured (SMTP_USER missing)")
    try:
        send_email(
            to=to,
            subject="✅ Test Email — Foodstuff Store",
            html=f"""
            <div style="font-family:Arial,sans-serif;max-width:560px">
              <h2 style="color:#1a5276">Email Test Successful</h2>
              <p>This is a test email sent from <b>Foodstuff Store</b>.</p>
              <table style="border-collapse:collapse;width:100%;margin:16px 0">
                <tr style="background:#f2f4f6">
                  <td style="padding:8px;font-weight:bold">SMTP Host</td>
                  <td style="padding:8px">{SMTP_HOST}</td>
                </tr>
                <tr>
                  <td style="padding:8px;font-weight:bold">Sent By</td>
                  <td style="padding:8px">{current_user.full_name} ({current_user.email or current_user.username})</td>
                </tr>
              </table>
              <p style="color:#1e8449;font-weight:bold">✅ If you received this, your email configuration is working correctly.</p>
            </div>""",
            text=f"Test email from Foodstuff Store via {SMTP_HOST}. SMTP is working correctly.",
        )
        return {"message": f"Test email sent to {to}", "smtp_host": SMTP_HOST}
    except Exception as exc:
        raise HTTPException(502, f"Email failed: {exc}")


def list_settings(db: Session) -> List[models.AppSetting]:
    return db.query(models.AppSetting).order_by(models.AppSetting.key).all()


def get_setting(db: Session, key: str) -> models.AppSetting:
    s = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if not s:
        raise HTTPException(404, f"Setting '{key}' not found")
    return s


def update_setting(db: Session, key: str, body: schemas.SettingUpdate, current_user: models.User) -> models.AppSetting:
    s = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if not s:
        s = models.AppSetting(key=key, value=body.value, updated_by=current_user.id)
        db.add(s)
    else:
        old_val = s.value
        s.value = body.value
        s.updated_by = current_user.id
        audit.log(
            db,
            models.AuditAction.update,
            models.AuditEntity.setting,
            s.id,
            current_user.id,
            old_values={"key": key, "value": old_val},
            new_values={"key": key, "value": body.value},
        )
    db.commit()
    db.refresh(s)
    return s


def bulk_update_settings(
    db: Session, body: List[schemas.SettingUpdate], current_user: models.User
) -> List[models.AppSetting]:
    updated = []
    for item in body:
        s = db.query(models.AppSetting).filter(models.AppSetting.key == item.key).first()
        if not s:
            s = models.AppSetting(key=item.key, value=item.value, updated_by=current_user.id)
            db.add(s)
        else:
            s.value = item.value
            s.updated_by = current_user.id
        updated.append(s)
    db.commit()
    for s in updated:
        db.refresh(s)
    return updated
