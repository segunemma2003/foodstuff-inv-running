"""
Pricing engine.

Final Selling Price = Cost Price + Supply Markup + Delivery Markup
                      + Payment Term Markup [+ WHT Markup when enabled]

Default markups (seeded in DB, editable via /pricing-rules):
  Supply   : 5 %
  Delivery : 3 %  (only when delivery_type == "delivery")
  Net 30   : 3.5% (only when payment_term == "net_30")
  WHT      : 5.4% (optional, baked into unit price — not a separate invoice line)
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session
import models


WHT_RATE = Decimal("0.054")  # 5.4% — applied on cost like other markups when enabled


def _round(value: Decimal) -> int:
    """Round to nearest kobo (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_active_rules(db: Session) -> dict:
    """Return a dict with active supply, delivery, payment_term, and "other" rules.

    supply/delivery are singleton slots (only one row of each type should ever
    be active — enforced at creation in pricing_rule_service.create_rule).
    "other" is NOT a singleton: every active "other" rule (cash back, promos,
    etc.) is collected and applied on top of supply/delivery/payment_term —
    see calculate_item_price. This is what keeps a newly added rule from ever
    silently replacing the supply markup again.
    """
    rules = (
        db.query(models.PricingRule)
        .filter(models.PricingRule.is_active == True)
        .order_by(models.PricingRule.effective_date.asc())
        .all()
    )
    supply_rule = None
    delivery_rule = None
    payment_term_rules: dict[str, models.PricingRule] = {}
    other_rules: list[models.PricingRule] = []

    for r in rules:
        if r.rule_type == models.PricingRuleType.supply:
            supply_rule = r
        elif r.rule_type == models.PricingRuleType.delivery:
            delivery_rule = r
        elif r.rule_type == models.PricingRuleType.payment_term and r.payment_term_code:
            payment_term_rules[r.payment_term_code] = r
        elif r.rule_type == models.PricingRuleType.other:
            other_rules.append(r)

    return {
        "supply": supply_rule,
        "delivery": delivery_rule,
        "payment_terms": payment_term_rules,
        "other": other_rules,
    }


def resolve_extra_charges(db: Session, rule_ids: list[int], subtotal: int) -> tuple[list[dict], int]:
    """Resolve admin-picked "other" rules attached to ONE invoice/quotation only.

    Supply markup is always global. An "other" rule is either global (active
    — auto-applied to every document via get_active_rules/calculate_item_price
    above) OR attached individually to a single document, never both — so
    only INACTIVE "other" rules are eligible here; picking an active one would
    double-count it. Computed on the document subtotal (post line items, same
    base as handling_charge/vat), snapshotted so later edits to the rule don't
    retroactively change this document's total.
    """
    if not rule_ids:
        return [], 0

    rules = (
        db.query(models.PricingRule)
        .filter(models.PricingRule.id.in_(rule_ids))
        .all()
    )
    found = {r.id: r for r in rules}
    charges = []
    total = 0
    for rid in rule_ids:
        r = found.get(rid)
        if not r:
            raise ValueError(f"Pricing rule {rid} not found")
        if r.rule_type != models.PricingRuleType.other:
            raise ValueError(f"Rule '{r.rule_name}' is not an \"other\" rule — only other-type rules can be attached individually")
        if r.is_active:
            raise ValueError(
                f"Rule '{r.rule_name}' is currently active globally — it already applies to every "
                f"invoice/quotation. Deactivate it first if you want to attach it to this document only."
            )
        pct = Decimal(str(r.markup_percentage))
        amount = _round(Decimal(str(subtotal)) * pct / 100)
        total += amount
        charges.append({
            "rule_id": r.id,
            "name": r.rule_name,
            "pct": float(pct),
            "amount": amount,
        })
    return charges, total


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
    *,
    wht_enabled: bool = False,
) -> dict:
    """
    Calculate per-unit pricing breakdown.

    When wht_enabled, 5.4% WHT is added on cost alongside other markups and
    included in unit_price (no separate customer-facing WHT line).
    """
    cost_price = Decimal(str(cost_price))

    supply_rule = rules.get("supply")
    supply_pct = (
        Decimal(str(supply_rule.markup_percentage)) / 100
        if supply_rule
        else Decimal("0.05")
    )
    supply_amount = _round(cost_price * supply_pct)

    delivery_pct = Decimal("0")
    delivery_amount = 0
    if delivery_type == models.DeliveryType.delivery or delivery_type == "delivery":
        delivery_rule = rules.get("delivery")
        if delivery_rule:
            delivery_pct = Decimal(str(delivery_rule.markup_percentage)) / 100
            delivery_amount = _round(cost_price * delivery_pct)

    pt_pct = Decimal("0")
    pt_amount = 0
    pt_rules = rules.get("payment_terms", {})
    pt_key = "immediate" if payment_term == "cash" else payment_term
    if pt_key in pt_rules:
        pt_rule = pt_rules[pt_key]
        pt_pct = Decimal(str(pt_rule.markup_percentage)) / 100
        pt_amount = _round(cost_price * pt_pct)

    wht_pct = WHT_RATE if wht_enabled else Decimal("0")
    wht_amount = _round(cost_price * wht_pct) if wht_enabled else 0

    # "Other" rules (cash back, promos, ...) — additive on top of everything
    # above, never a replacement for the supply markup. Multiple can be active
    # at once; each is applied on cost price and summed.
    other_rules = rules.get("other") or []
    other_breakdown = []
    other_amount = 0
    for r in other_rules:
        r_pct = Decimal(str(r.markup_percentage)) / 100
        r_amount = _round(cost_price * r_pct)
        other_amount += r_amount
        other_breakdown.append({
            "rule_id": r.id,
            "rule_name": r.rule_name,
            "pct": float(r_pct * 100),
            "amount": r_amount,
        })

    unit_price = (
        int(cost_price) + supply_amount + delivery_amount + pt_amount + wht_amount + other_amount
    )

    return {
        "supply_markup_pct": float(supply_pct * 100),
        "supply_markup_amount": supply_amount,
        "delivery_markup_pct": float(delivery_pct * 100),
        "delivery_markup_amount": delivery_amount,
        "payment_term_markup_pct": float(pt_pct * 100),
        "payment_term_markup_amount": pt_amount,
        "wht_markup_pct": float(wht_pct * 100),
        "wht_markup_amount": wht_amount,
        "other_markup_amount": other_amount,
        "other_markup_breakdown": other_breakdown,
        "unit_price": unit_price,
    }
