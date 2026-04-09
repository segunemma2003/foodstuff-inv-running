from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin, require_admin_or_manager
from auth import hash_password
import models
import schemas
from utils import audit

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
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    if is_active is not None:
        q = q.filter(models.User.is_active == is_active)
    return q.offset(skip).limit(limit).all()


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    if db.query(models.User).filter(
        (models.User.username == body.username) | (models.User.email == body.email)
    ).first():
        raise HTTPException(400, "Username or email already exists")

    user = models.User(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.flush()
    audit.log(db, models.AuditAction.create, models.AuditEntity.user, user.id,
               current_user.id, description=f"Created user {user.username}")
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    old = {"role": user.role.value, "is_active": user.is_active, "email": user.email}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    audit.log(db, models.AuditAction.update, models.AuditEntity.user, user.id,
               current_user.id, old_values=old,
               new_values=body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=schemas.MessageResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == current_user.id:
        raise HTTPException(400, "Cannot deactivate yourself")
    user.is_active = False
    audit.log(db, models.AuditAction.deactivate, models.AuditEntity.user, user.id,
               current_user.id, description=f"Deactivated user {user.username}")
    db.commit()
    return schemas.MessageResponse(message="User deactivated")
