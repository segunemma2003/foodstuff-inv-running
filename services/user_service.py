"""User domain service."""

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth import hash_password
import models
import schemas
from repositories import user_repository as user_repo
from utils import audit
from utils.email import tpl_password_changed
from services.integrations.tasks import send_email_task


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


def change_user_password(
    db: Session,
    user_id: int,
    body: schemas.AdminUserPasswordChange,
    current_user: models.User,
) -> schemas.MessageResponse:
    user = user_repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    user.hashed_password = hash_password(body.new_password)
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.user,
        user.id,
        current_user.id,
        description=f"Reset password for user {user.username}",
    )
    db.commit()
    if user.email:
        subject, html, text = tpl_password_changed(
            user.full_name,
            body.new_password,
            current_user.full_name or current_user.username,
        )
        send_email_task.delay(user.email, subject, html, text)
    return schemas.MessageResponse(message="User password changed successfully")


def reset_user_password(
    db: Session,
    user_id: int,
    body: schemas.AdminUserPasswordChange,
    current_user: models.User,
) -> schemas.MessageResponse:
    """Backward-compatible alias for older clients."""
    return change_user_password(db, user_id, body, current_user)
