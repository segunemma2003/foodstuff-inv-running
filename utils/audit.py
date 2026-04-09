import json
from typing import Optional
from sqlalchemy.orm import Session
import models


def log(
    db: Session,
    action: models.AuditAction,
    entity_type: models.AuditEntity,
    entity_id: Optional[int],
    user_id: Optional[int],
    description: Optional[str] = None,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
):
    entry = models.AuditTrail(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        description=description,
        old_values=json.dumps(old_values) if old_values else None,
        new_values=json.dumps(new_values) if new_values else None,
    )
    db.add(entry)
    # Caller is responsible for committing
