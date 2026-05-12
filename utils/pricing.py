"""
Pricing engine.

Final Selling Price = Cost Price + Supply Markup + Delivery Markup + Payment Term Markup

Default markups (seeded in DB, editable via /pricing-rules):
  Supply   : 5 %
  Delivery : 3 %  (only when delivery_type == "delivery")
  Net 30   : 3.5% (only when payment_term == "net_30")
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
import models


def _round(value: Decimal) -> int:
    """Round to nearest kobo (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_active_rules(db: Session) -> dict:
    """Return a dict with active supply, delivery and payment_term rules."""
    rules = (
        db.query(models.PricingRule)
        .filter(models.PricingRule.is_active == True)
        .all()
    )
    supply_rule = None
    delivery_rule = None
    payment_term_rules: dict[str, models.PricingRule] = {}

    for r in rules:
        if r.rule_type == models.PricingRuleType.supply:
            supply_rule = r
        elif r.rule_type == models.PricingRuleType.delivery:
            delivery_rule = r
        elif r.rule_type == models.PricingRuleType.payment_term and r.payment_term_code:
            payment_term_rules[r.payment_term_code] = r

    return {
        "supply": supply_rule,
        "delivery": delivery_rule,
        "payment_terms": payment_term_rules,
    }


def get_current_cost(product_id: int, db: Session) -> Optional[Decimal]:
    today = date.today()
    record = (
        db.query(models.CostPrice)
        .filter(
            models.CostPrice.product_id == product_id,
            models.CostPrice.effective_date <= today,
        )
        .order_by(models.CostPrice.effective_date.desc())
        .first()
    )
    return Decimal(str(record.cost_price)) if record else None


def calculate_item_price(
    cost_price: Decimal,
    delivery_type: str,
    payment_term: str,
    rules: dict,
) -> dict:
    """
    Calculate per-unit pricing breakdown.

    Returns a dict with all markup values and the final unit_price.
    """
    cost_price = Decimal(str(cost_price))

    # Supply markup (always applied)
    supply_rule = rules.get("supply")
    supply_pct = (
        Decimal(str(supply_rule.markup_percentage)) / 100
        if supply_rule
        else Decimal("0.05")  # fallback default
    )
    supply_amount = _round(cost_price * supply_pct)

    # Delivery markup (only if delivery)
    delivery_pct = Decimal("0")
    delivery_amount = Decimal("0")
    if delivery_type == models.DeliveryType.delivery or delivery_type == "delivery":
        delivery_rule = rules.get("delivery")
        if delivery_rule:
            delivery_pct = Decimal(str(delivery_rule.markup_percentage)) / 100
            delivery_amount = _round(cost_price * delivery_pct)

    # Payment term markup
    pt_pct = Decimal("0")
    pt_amount = Decimal("0")
    pt_rules = rules.get("payment_terms", {})
    if payment_term in pt_rules:
        pt_rule = pt_rules[payment_term]
        pt_pct = Decimal(str(pt_rule.markup_percentage)) / 100
        pt_amount = _round(cost_price * pt_pct)

    unit_price = int(cost_price) + supply_amount + delivery_amount + pt_amount

    return {
        "supply_markup_pct": float(supply_pct * 100),
        "supply_markup_amount": supply_amount,        # kobo (int)
        "delivery_markup_pct": float(delivery_pct * 100),
        "delivery_markup_amount": delivery_amount,    # kobo (int)
        "payment_term_markup_pct": float(pt_pct * 100),
        "payment_term_markup_amount": pt_amount,      # kobo (int)
        "unit_price": unit_price,                     # kobo (int)
    }
