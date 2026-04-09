import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from auth import verify_password, hash_password, create_access_token
from dependencies import get_current_user
import models
import schemas
from utils import audit
from utils.email import tpl_password_reset
from utils.tasks import send_email_task

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = (
        db.query(models.User)
        .filter(
            (models.User.username == form.username) | (models.User.email == form.username)
        )
        .first()
    )
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    token = create_access_token({"sub": str(user.id)})
    audit.log(db, models.AuditAction.login, models.AuditEntity.user, user.id, user.id,
               description=f"User {user.username} logged in")
    db.commit()
    return schemas.TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password", response_model=schemas.MessageResponse)
def forgot_password(req: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Generates a reset token, stores it in the DB, and queues an email via Celery.
    Always returns 200 so we don't reveal whether the email is registered.
    The API returns in < 5 ms — SMTP happens in the worker.
    """
    user = db.query(models.User).filter(models.User.email == req.email).first()
    if user and user.is_active:
        # Invalidate any existing unexpired tokens for this user
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

        # Queue email — fire and forget; API does NOT wait for SMTP
        subject, html, text = tpl_password_reset(user.full_name, token_str)
        send_email_task.delay(user.email, subject, html, text)

    return schemas.MessageResponse(message="If that email is registered, a reset link has been sent.")


@router.post("/reset-password", response_model=schemas.MessageResponse)
def reset_password(req: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
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


@router.post("/change-password", response_model=schemas.MessageResponse)
def change_password(
    req: schemas.UserPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(req.new_password)
    db.commit()
    return schemas.MessageResponse(message="Password updated successfully")
