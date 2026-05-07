"""Pricing rules domain."""

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit


def list_rules(db: Session, is_active: Optional[bool] = None) -> List[models.PricingRule]:
    pricing_rule_query = db.query(models.PricingRule)
    if is_active is not None:
        pricing_rule_query = pricing_rule_query.filter(models.PricingRule.is_active == is_active)
    return pricing_rule_query.order_by(models.PricingRule.rule_type, models.PricingRule.rule_name).all()


def bulk_delete(db: Session, body: schemas.BulkIdsRequest, current_user: models.User) -> schemas.BulkDeleteResult:
    result = schemas.BulkDeleteResult()
    for rid in body.ids:
        rule = db.query(models.PricingRule).filter(models.PricingRule.id == rid).first()
        if not rule:
            result.failed.append({"id": rid, "detail": "Pricing rule not found"})
            continue
        audit.log(
            db,
            models.AuditAction.delete,
            models.AuditEntity.pricing_rule,
            rule.id,
            current_user.id,
            description=f"Deleted pricing rule: {rule.rule_name}",
        )
        db.delete(rule)
        result.deleted += 1
    db.commit()
    return result


def create_rule(db: Session, body: schemas.PricingRuleCreate, current_user: models.User) -> models.PricingRule:
    if body.rule_type == models.PricingRuleType.payment_term and not body.payment_term_code:
        raise HTTPException(400, "payment_term_code required for payment_term rule type")

    rule = models.PricingRule(
        **body.model_dump(),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(rule)
    db.flush()
    audit.log(
        db,
        models.AuditAction.create,
        models.AuditEntity.pricing_rule,
        rule.id,
        current_user.id,
        description=f"Created pricing rule: {rule.rule_name}",
    )
    db.commit()
    db.refresh(rule)
    return rule


def get_rule(db: Session, rule_id: int) -> models.PricingRule:
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")
    return rule


def update_rule(
    db: Session, rule_id: int, body: schemas.PricingRuleUpdate, current_user: models.User
) -> models.PricingRule:
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")

    old = {"markup_percentage": str(rule.markup_percentage), "is_active": rule.is_active}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    rule.updated_by = current_user.id
    audit.log(
        db,
        models.AuditAction.update,
        models.AuditEntity.pricing_rule,
        rule.id,
        current_user.id,
        old_values=old,
        new_values=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule_id: int, current_user: models.User) -> schemas.MessageResponse:
    rule = db.query(models.PricingRule).filter(models.PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Pricing rule not found")
    audit.log(
        db,
        models.AuditAction.delete,
        models.AuditEntity.pricing_rule,
        rule.id,
        current_user.id,
        description=f"Deleted pricing rule: {rule.rule_name}",
    )
    db.delete(rule)
    db.commit()
    return schemas.MessageResponse(message="Pricing rule deleted")
