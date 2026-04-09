from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager
import models
import schemas
from utils import audit

router = APIRouter(prefix="/settings", tags=["Settings"])


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
