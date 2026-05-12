-- =============================================================================
-- Revert: the migrate_to_kobo.sql script multiplied values that were already
-- stored in kobo (the frontend was already converting naira → kobo before
-- sending to the API). This script divides all monetary columns back by 100
-- so each value is once again a correct kobo integer.
--
-- Run on Heroku:
--   heroku pg:psql -a <your-app-name> < revert_kobo_migration.sql
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
  delivery_fee = ROUND(delivery_fee / 100);

UPDATE invoice_items SET
  cost_price                 = ROUND(cost_price / 100),
  supply_markup_amount       = ROUND(supply_markup_amount / 100),
  delivery_markup_amount     = ROUND(delivery_markup_amount / 100),
  payment_term_markup_amount = ROUND(payment_term_markup_amount / 100),
  unit_price                 = ROUND(unit_price / 100),
  line_total                 = ROUND(line_total / 100);

UPDATE invoices SET
  total_amount = ROUND(total_amount / 100),
  delivery_fee = ROUND(delivery_fee / 100),
  amount_paid  = ROUND(amount_paid / 100);

COMMIT;
