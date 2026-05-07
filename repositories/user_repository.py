"""User persistence helpers."""

from typing import List, Optional

from sqlalchemy.orm import Session

import models


def list_users(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[models.User]:
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    if is_active is not None:
        q = q.filter(models.User.is_active == is_active)
    return q.offset(skip).limit(limit).all()


def get_by_id(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def find_by_username_or_email(db: Session, username: str, email: str) -> Optional[models.User]:
    return (
        db.query(models.User)
        .filter((models.User.username == username) | (models.User.email == email))
        .first()
    )


def find_login_user(db: Session, username_or_email: str) -> Optional[models.User]:
    return (
        db.query(models.User)
        .filter(
            (models.User.username == username_or_email) | (models.User.email == username_or_email)
        )
        .first()
    )
