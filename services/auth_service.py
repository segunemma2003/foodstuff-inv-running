"""Authentication and password flows."""

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from auth import verify_password, hash_password, create_access_token
import models
import schemas
from repositories import user_repository as user_repo
from utils import audit
from utils.email import tpl_password_reset
from services.integrations.tasks import send_email_task


def login(db: Session, username: str, password: str) -> schemas.TokenResponse:
    user = user_repo.find_login_user(db, username)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    token = create_access_token({"sub": str(user.id)})
    audit.log(
        db,
        models.AuditAction.login,
        models.AuditEntity.user,
        user.id,
        user.id,
        description=f"User {user.username} logged in",
    )
    db.commit()
    return schemas.TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


def forgot_password(db: Session, req: schemas.ForgotPasswordRequest) -> schemas.MessageResponse:
    user = db.query(models.User).filter(models.User.email == req.email).first()
    if user and user.is_active:
        db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.user_id == user.id,
            models.PasswordResetToken.used == False,
            models.PasswordResetToken.expires_at > datetime.utcnow(),
        ).update({"used": True})

        token_str = secrets.token_urlsafe(32)
        reset_token = models.PasswordResetToken(
            token=token_str,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(reset_token)
        db.commit()

        subject, html, text = tpl_password_reset(user.full_name, token_str)
        send_email_task.delay(user.email, subject, html, text)

    return schemas.MessageResponse(message="If that email is registered, a reset link has been sent.")


def reset_password(db: Session, req: schemas.ResetPasswordRequest) -> schemas.MessageResponse:
    record = (
        db.query(models.PasswordResetToken)
        .filter(
            models.PasswordResetToken.token == req.token,
            models.PasswordResetToken.used == False,
            models.PasswordResetToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(models.User).filter(models.User.id == record.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="User account not found or inactive")

    user.hashed_password = hash_password(req.new_password)
    record.used = True
    db.commit()
    return schemas.MessageResponse(message="Password has been reset successfully")


def change_password(db: Session, current_user: models.User, req: schemas.UserPasswordUpdate) -> schemas.MessageResponse:
    if not verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(req.new_password)
    db.commit()
    return schemas.MessageResponse(message="Password updated successfully")
