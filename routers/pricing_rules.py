from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import (
    get_current_user,
    require_admin_or_manager,
    require_admin_manager_or_operations,
    require_admin,
)
import models
import schemas
from services import pricing_rule_service

router = APIRouter(prefix="/pricing-rules", tags=["Pricing Rules"])


@router.get("", response_model=List[schemas.PricingRuleOut])
def list_rules(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return pricing_rule_service.list_rules(db, is_active=is_active)


@router.post("/bulk-delete", response_model=schemas.BulkDeleteResult)
def bulk_delete_pricing_rules(
    body: schemas.BulkIdsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return pricing_rule_service.bulk_delete(db, body, current_user)


@router.post("", response_model=schemas.PricingRuleOut, status_code=201)
def create_rule(
    body: schemas.PricingRuleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return pricing_rule_service.create_rule(db, body, current_user)


@router.get("/{rule_id}", response_model=schemas.PricingRuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return pricing_rule_service.get_rule(db, rule_id)


@router.put("/{rule_id}", response_model=schemas.PricingRuleOut)
def update_rule(
    rule_id: int,
    body: schemas.PricingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_manager_or_operations),
):
    return pricing_rule_service.update_rule(db, rule_id, body, current_user)


@router.delete("/{rule_id}", response_model=schemas.MessageResponse)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return pricing_rule_service.delete_rule(db, rule_id, current_user)
