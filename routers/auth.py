from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
import models
import schemas
from services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return auth_service.login(db, form.username, form.password)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password", response_model=schemas.MessageResponse)
def forgot_password(req: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    return auth_service.forgot_password(db, req)


@router.post("/reset-password", response_model=schemas.MessageResponse)
def reset_password(req: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    return auth_service.reset_password(db, req)


@router.post("/change-password", response_model=schemas.MessageResponse)
def change_password(
    req: schemas.UserPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return auth_service.change_password(db, current_user, req)
