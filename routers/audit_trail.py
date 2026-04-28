from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_admin_or_manager
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
    _: models.User = Depends(require_admin_or_manager),
):
    audit_trail_query = db.query(models.AuditTrail)
    if entity_type:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.entity_type == entity_type)
    if entity_id:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.entity_id == entity_id)
    if user_id:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.user_id == user_id)
    if action:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.action == action)
    if date_from:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.timestamp >= date_from)
    if date_to:
        audit_trail_query = audit_trail_query.filter(models.AuditTrail.timestamp <= date_to)
    return audit_trail_query.order_by(models.AuditTrail.timestamp.desc()).offset(skip).limit(limit).all()
