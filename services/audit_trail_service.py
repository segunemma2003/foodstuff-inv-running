"""Audit trail read queries."""

from typing import List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

import models
import schemas


def list_audit_trail(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[models.AuditTrail]:
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
