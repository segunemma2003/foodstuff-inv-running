"""Pricing rules domain."""

from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from utils import audit


def list_rules(
    db: Session, is_active: Optional[bool] = None, rule_type: Optional[str] = None
) -> List[models.PricingRule]:
    pricing_rule_query = db.query(models.PricingRule)
    if is_active is not None:
        pricing_rule_query = pricing_rule_query.filter(models.PricingRule.is_active == is_active)
    if rule_type is not None:
        pricing_rule_query = pricing_rule_query.filter(models.PricingRule.rule_type == rule_type)
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

    # supply/delivery are singleton slots — get_active_rules() keeps only the
    # last one it sees, so a second active row of the same type silently
    # shadows the first (this is exactly how "Cash Back Rule" wiped out the
    # 7% supply markup: it was created as rule_type=supply instead of other).
    # A second payment_term rule for the same code has the same problem.
    # Block it here instead: point the admin at editing the existing rule, or
    # at rule_type="other" if what they actually want is an additional,
    # stacking markup (cash back, promos, ...).
    if body.is_active and body.rule_type in (models.PricingRuleType.supply, models.PricingRuleType.delivery):
        clash = (
            db.query(models.PricingRule)
            .filter(
                models.PricingRule.rule_type == body.rule_type,
                models.PricingRule.is_active == True,
            )
            .first()
        )
        if clash:
            raise HTTPException(
                400,
                f"An active {body.rule_type.value} rule already exists ('{clash.rule_name}', "
                f"{clash.markup_percentage}%). Edit or deactivate it instead of creating a second "
                f"one — only one active {body.rule_type.value} rule is used at a time. If you meant "
                f"to add an extra, stacking charge (e.g. cash back), use rule_type=\"other\".",
            )
    if body.is_active and body.rule_type == models.PricingRuleType.payment_term and body.payment_term_code:
        clash = (
            db.query(models.PricingRule)
            .filter(
                models.PricingRule.rule_type == models.PricingRuleType.payment_term,
                models.PricingRule.payment_term_code == body.payment_term_code,
                models.PricingRule.is_active == True,
            )
            .first()
        )
        if clash:
            raise HTTPException(
                400,
                f"An active payment_term rule for '{body.payment_term_code}' already exists "
                f"('{clash.rule_name}', {clash.markup_percentage}%). Edit or deactivate it instead "
                f"of creating a second one.",
            )

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

    # Reactivating a supply/delivery/payment_term rule can shadow another
    # already-active one of the same type — same guard as create_rule.
    will_be_active = body.is_active if body.is_active is not None else rule.is_active
    if will_be_active and not rule.is_active and rule.rule_type in (
        models.PricingRuleType.supply, models.PricingRuleType.delivery,
    ):
        clash = (
            db.query(models.PricingRule)
            .filter(
                models.PricingRule.rule_type == rule.rule_type,
                models.PricingRule.is_active == True,
                models.PricingRule.id != rule.id,
            )
            .first()
        )
        if clash:
            raise HTTPException(
                400,
                f"An active {rule.rule_type.value} rule already exists ('{clash.rule_name}', "
                f"{clash.markup_percentage}%). Deactivate it first.",
            )

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
