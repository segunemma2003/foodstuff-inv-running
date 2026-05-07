"""User domain service."""

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth import hash_password
import models
import schemas
from repositories import user_repository as user_repo
from utils import audit


def list_users(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[models.User]:
    return user_repo.list_users(db, skip=skip, limit=limit, role=role, is_active=is_active)


def create_user(db: Session, body: schemas.UserCreate, current_user: models.User) -> models.User:
    if user_repo.find_by_username_or_email(db, body.username, body.email):
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
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.user,
        user.id,
        current_user.id,
        description=f"Created user {user.username}",
    )
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: int) -> models.User:
    user = user_repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


def update_user(db: Session, user_id: int, body: schemas.UserUpdate, current_user: models.User) -> models.User:
    user = user_repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    old = {"role": user.role.value, "is_active": user.is_active, "email": user.email}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.user,
        user.id,
        current_user.id,
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user_id: int, current_user: models.User) -> schemas.MessageResponse:
    user = user_repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == current_user.id:
        raise HTTPException(400, "Cannot deactivate yourself")
    user.is_active = False
    audit.log(
        db,
        models.AuditAction.deactivate,
        models.AuditEntity.user,
        user.id,
        current_user.id,
        description=f"Deactivated user {user.username}",
    )
    db.commit()
    return schemas.MessageResponse(message="User deactivated")
