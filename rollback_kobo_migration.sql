-- =============================================================================
-- ROLLBACK: undo the ×100 migration (divide all monetary columns back by 100)
-- Run this if the migration made figures 100× too large.
--
-- heroku pg:psql -a fss-newinventory < rollback_kobo_migration.sql
-- OR
-- psql "$(heroku config:get DATABASE_URL -a fss-newinventory)" < rollback_kobo_migration.sql
-- =============================================================================

BEGIN;

UPDATE cost_prices
SET cost_price = ROUND(cost_price / 100);

UPDATE quotation_items SET
  cost_price                 = ROUND(cost_price / 100),
  supply_markup_amount       = ROUND(supply_markup_amount / 100),
  delivery_markup_amount     = ROUND(delivery_markup_amount / 100),
  payment_term_markup_amount = ROUND(payment_term_markup_amount / 100),
  unit_price                 = ROUND(unit_price / 100),
  line_total                 = ROUND(line_total / 100);

UPDATE quotations SET
  total_amount = ROUND(total_amount / 100),
  delivery_fee = ROUND(COALESCE(delivery_fee, 0) / 100);

UPDATE invoice_items SET
  cost_price                 = ROUND(cost_price / 100),
  supply_markup_amount       = ROUND(supply_markup_amount / 100),
  delivery_markup_amount     = ROUND(delivery_markup_amount / 100),
  payment_term_markup_amount = ROUND(payment_term_markup_amount / 100),
  unit_price                 = ROUND(unit_price / 100),
  line_total                 = ROUND(line_total / 100);

UPDATE invoices SET
  total_amount = ROUND(total_amount / 100),
  delivery_fee = ROUND(COALESCE(delivery_fee, 0) / 100),
  amount_paid  = ROUND(COALESCE(amount_paid, 0) / 100);

COMMIT;
