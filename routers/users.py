from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_admin, require_admin_or_manager
import models
import schemas
from services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=List[schemas.UserOut])
def list_users(
    skip: int = 0,
    limit: int = 50,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    return user_service.list_users(db, skip=skip, limit=limit, role=role, is_active=is_active)


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return user_service.create_user(db, body, current_user)


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    return user_service.get_user(db, user_id)


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return user_service.update_user(db, user_id, body, current_user)


@router.delete("/{user_id}", response_model=schemas.MessageResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return user_service.deactivate_user(db, user_id, current_user)
