-- Migration 020: ZATCA metadata columns for products
-- Adds dedicated columns used by e-invoice classification and customs metadata.

ALTER TABLE products ADD COLUMN tax_category TEXT DEFAULT 'S';
ALTER TABLE products ADD COLUMN hs_code TEXT;
ALTER TABLE products ADD COLUMN origin_country TEXT;
ALTER TABLE products ADD COLUMN tax_exemption_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_products_tax_category ON products(tax_category);
