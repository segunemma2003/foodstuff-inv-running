from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager
import models
import schemas
from utils import audit

router = APIRouter(prefix="/settings", tags=["Settings"])


class TestEmailRequest(BaseModel):
    to: str


@router.post("/test-email")
def send_test_email(
    body: TestEmailRequest,
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Send a test email to verify SMTP configuration. Admin/manager only."""
    from utils.email import send_email, SMTP_HOST, SMTP_USER
    if not SMTP_USER:
        raise HTTPException(503, "SMTP is not configured (SMTP_USER missing)")
    try:
        send_email(
            to=body.to,
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
        return {"message": f"Test email sent to {body.to}", "smtp_host": SMTP_HOST}
    except Exception as exc:
        raise HTTPException(502, f"Email failed: {exc}")


@router.get("", response_model=List[schemas.SettingOut])
def list_settings(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return db.query(models.AppSetting).order_by(models.AppSetting.key).all()


@router.get("/{key}", response_model=schemas.SettingOut)
def get_setting(
    key: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    s = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if not s:
        raise HTTPException(404, f"Setting '{key}' not found")
    return s


@router.put("/{key}", response_model=schemas.SettingOut)
def update_setting(
    key: str,
    body: schemas.SettingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    s = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if not s:
        # create new setting
        s = models.AppSetting(key=key, value=body.value, updated_by=current_user.id)
        db.add(s)
    else:
        old_val = s.value
        s.value = body.value
        s.updated_by = current_user.id
        audit.log(db, models.AuditAction.update, models.AuditEntity.setting, s.id,
                   current_user.id,
                   old_values={"key": key, "value": old_val},
                   new_values={"key": key, "value": body.value})
    db.commit()
    db.refresh(s)
    return s


@router.put("", response_model=List[schemas.SettingOut])
def bulk_update_settings(
    body: List[schemas.SettingUpdate],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
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
