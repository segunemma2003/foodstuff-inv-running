from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager
import models
import schemas
from services import settings_service

router = APIRouter(prefix="/settings", tags=["Settings"])


class TestEmailRequest(BaseModel):
    to: str


@router.post("/test-email")
def send_test_email(
    body: TestEmailRequest,
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Send a test email to verify SMTP configuration. Admin/manager only."""
    return settings_service.send_test_email(body.to, current_user)


@router.get("", response_model=List[schemas.SettingOut])
def list_settings(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return settings_service.list_settings(db)


@router.get("/{key}", response_model=schemas.SettingOut)
def get_setting(
    key: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return settings_service.get_setting(db, key)


@router.put("/{key}", response_model=schemas.SettingOut)
def update_setting(
    key: str,
    body: schemas.SettingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return settings_service.update_setting(db, key, body, current_user)


@router.put("", response_model=List[schemas.SettingOut])
def bulk_update_settings(
    body: List[schemas.SettingUpdate],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    return settings_service.bulk_update_settings(db, body, current_user)
