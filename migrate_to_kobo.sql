-- =============================================================================
-- Migration: convert monetary columns from naira (NUMERIC) → kobo (BIGINT)
-- Also adds discount_pct column to quotation_items.
--
-- Run on Heroku:
--   heroku pg:psql -a <your-app-name> < migrate_to_kobo.sql
-- Or paste directly into the Heroku Postgres console.
-- =============================================================================

BEGIN;

-- ─── 1. Add missing discount_pct column ──────────────────────────────────────
ALTER TABLE quotation_items
  ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(6, 3) NOT NULL DEFAULT 0;

-- ─── 2. Multiply every monetary amount by 100 (naira → kobo) ─────────────────

UPDATE cost_prices
SET cost_price = ROUND(cost_price * 100);

UPDATE quotation_items SET
  cost_price                 = ROUND(COALESCE(cost_price, 0) * 100),
  supply_markup_amount       = ROUND(COALESCE(supply_markup_amount, 0) * 100),
  delivery_markup_amount     = ROUND(COALESCE(delivery_markup_amount, 0) * 100),
  payment_term_markup_amount = ROUND(COALESCE(payment_term_markup_amount, 0) * 100),
  unit_price                 = ROUND(COALESCE(unit_price, 0) * 100),
  line_total                 = ROUND(COALESCE(line_total, 0) * 100);

UPDATE quotations SET
  total_amount = ROUND(COALESCE(total_amount, 0) * 100),
  delivery_fee = ROUND(COALESCE(delivery_fee, 0) * 100);

UPDATE invoice_items SET
  cost_price                 = ROUND(COALESCE(cost_price, 0) * 100),
  supply_markup_amount       = ROUND(COALESCE(supply_markup_amount, 0) * 100),
  delivery_markup_amount     = ROUND(COALESCE(delivery_markup_amount, 0) * 100),
  payment_term_markup_amount = ROUND(COALESCE(payment_term_markup_amount, 0) * 100),
  unit_price                 = ROUND(COALESCE(unit_price, 0) * 100),
  line_total                 = ROUND(COALESCE(line_total, 0) * 100);

UPDATE invoices SET
  total_amount = ROUND(COALESCE(total_amount, 0) * 100),
  delivery_fee = ROUND(COALESCE(delivery_fee, 0) * 100),
  amount_paid  = ROUND(COALESCE(amount_paid, 0) * 100);

-- ─── 3. Change column types from NUMERIC(15,2) → BIGINT ──────────────────────

ALTER TABLE cost_prices
  ALTER COLUMN cost_price TYPE BIGINT USING cost_price::BIGINT;

ALTER TABLE quotation_items
  ALTER COLUMN cost_price                 TYPE BIGINT USING cost_price::BIGINT,
  ALTER COLUMN supply_markup_amount       TYPE BIGINT USING supply_markup_amount::BIGINT,
  ALTER COLUMN delivery_markup_amount     TYPE BIGINT USING delivery_markup_amount::BIGINT,
  ALTER COLUMN payment_term_markup_amount TYPE BIGINT USING payment_term_markup_amount::BIGINT,
  ALTER COLUMN unit_price                 TYPE BIGINT USING unit_price::BIGINT,
  ALTER COLUMN line_total                 TYPE BIGINT USING line_total::BIGINT;

ALTER TABLE quotations
  ALTER COLUMN total_amount TYPE BIGINT USING total_amount::BIGINT,
  ALTER COLUMN delivery_fee TYPE BIGINT USING delivery_fee::BIGINT;

ALTER TABLE invoice_items
  ALTER COLUMN cost_price                 TYPE BIGINT USING cost_price::BIGINT,
  ALTER COLUMN supply_markup_amount       TYPE BIGINT USING supply_markup_amount::BIGINT,
  ALTER COLUMN delivery_markup_amount     TYPE BIGINT USING delivery_markup_amount::BIGINT,
  ALTER COLUMN payment_term_markup_amount TYPE BIGINT USING payment_term_markup_amount::BIGINT,
  ALTER COLUMN unit_price                 TYPE BIGINT USING unit_price::BIGINT,
  ALTER COLUMN line_total                 TYPE BIGINT USING line_total::BIGINT;

ALTER TABLE invoices
  ALTER COLUMN total_amount TYPE BIGINT USING total_amount::BIGINT,
  ALTER COLUMN delivery_fee TYPE BIGINT USING delivery_fee::BIGINT,
  ALTER COLUMN amount_paid  TYPE BIGINT USING amount_paid::BIGINT;

COMMIT;
