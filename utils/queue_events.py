import json
from typing import Any

from sqlalchemy.orm import Session

import models


def log_queue_event(
    db: Session,
    *,
    task_id: str,
    event_type: str,
    title: str,
    requested_by: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    event = models.QueueEvent(
        task_id=task_id,
        event_type=event_type,
        title=title,
        requested_by=requested_by,
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(event)
    db.commit()
