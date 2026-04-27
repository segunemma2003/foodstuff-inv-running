from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_admin_manager_sales
import models
import schemas

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
    _: models.User = Depends(require_admin_manager_sales),
):
    q = db.query(models.AuditTrail)
    if entity_type:
        q = q.filter(models.AuditTrail.entity_type == entity_type)
    if entity_id:
        q = q.filter(models.AuditTrail.entity_id == entity_id)
    if user_id:
        q = q.filter(models.AuditTrail.user_id == user_id)
    if action:
        q = q.filter(models.AuditTrail.action == action)
    if date_from:
        q = q.filter(models.AuditTrail.timestamp >= date_from)
    if date_to:
        q = q.filter(models.AuditTrail.timestamp <= date_to)
    return q.order_by(models.AuditTrail.timestamp.desc()).offset(skip).limit(limit).all()
