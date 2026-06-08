-- Migration: add handling_charge columns to invoices table
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS handling_charge_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS handling_charge_amount BIGINT NOT NULL DEFAULT 0;
