from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_admin_or_manager, require_admin
import models
import schemas
from utils import audit

router = APIRouter(prefix="/pricing-rules", tags=["Pricing Rules"])


@router.get("", response_model=List[schemas.PricingRuleOut])
def list_rules(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    pricing_rule_query = db.query(models.PricingRule)
    if is_active is not None:
        pricing_rule_query = pricing_rule_query.filter(models.PricingRule.is_active == is_active)
    return pricing_rule_query.order_by(models.PricingRule.rule_type, models.PricingRule.rule_name).all()


@router.post("/bulk-delete", response_model=schemas.BulkDeleteResult)
def bulk_delete_pricing_rules(
    body: schemas.BulkIdsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    result = schemas.BulkDeleteResult()
    for rid in body.ids:
        rule = db.query(models.PricingRule).filter(models.PricingRule.id == rid).first()
        if not rule:
            result.failed.append({"id": rid, "detail": "Pricing rule not found"})
            continue
        audit.log(db, models.AuditAction.delete, models.AuditEntity.pricing_rule, rule.id,
                   current_user.id, description=f"Deleted pricing rule: {rule.rule_name}")
        db.delete(rule)
        result.deleted += 1
    db.commit()
    return result


@router.post("", response_model=schemas.PricingRuleOut, status_code=201)
def create_rule(
    body: schemas.PricingRuleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    if body.rule_type == models.PricingRuleType.payment_term and not body.payment_term_code:
        raise HTTPException(400, "payment_term_code required for payment_term rule type")

    rule = models.PricingRule(
        **body.model_dump(),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(rule)
    db.flush()
    audit.log(db, models.AuditAction.create, models.AuditEntity.pricing_rule, rule.id,
               current_user.id, description=f"Created pricing rule: {rule.rule_name}")
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/{rule_id}", response_model=schemas.PricingRuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")
    return rule


@router.put("/{rule_id}", response_model=schemas.PricingRuleOut)
def update_rule(
    rule_id: int,
    body: schemas.PricingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")

    old = {"markup_percentage": str(rule.markup_percentage), "is_active": rule.is_active}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    rule.updated_by = current_user.id
    audit.log(db, models.AuditAction.update, models.AuditEntity.pricing_rule, rule.id,
               current_user.id, old_values=old, new_values=body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", response_model=schemas.MessageResponse)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")
    audit.log(db, models.AuditAction.delete, models.AuditEntity.pricing_rule, rule.id,
               current_user.id, description=f"Deleted pricing rule: {rule.rule_name}")
    db.delete(rule)
    db.commit()
    return schemas.MessageResponse(message="Pricing rule deleted")
