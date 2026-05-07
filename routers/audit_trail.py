from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_admin_or_manager
import models
import schemas
from services import audit_trail_service

router = APIRouter(prefix="/audit-trail", tags=["Audit Trail"])


@router.get("", response_model=List[schemas.AuditTrailOut])
def list_audit_trail(
    skip: int = 0,
    limit: int = 100,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    return audit_trail_service.list_audit_trail(
        db,
        skip=skip,
        limit=limit,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
