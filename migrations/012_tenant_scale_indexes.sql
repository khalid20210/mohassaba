-- 012_tenant_scale_indexes.sql
-- تحسين أداء المنصة عند زيادة عدد الشركات (multi-tenant scale)

CREATE INDEX IF NOT EXISTS idx_users_business_id
ON users(business_id);

CREATE INDEX IF NOT EXISTS idx_roles_business_id
ON roles(business_id);

CREATE INDEX IF NOT EXISTS idx_contacts_business_id
ON contacts(business_id);

CREATE INDEX IF NOT EXISTS idx_products_business_id
ON products(business_id);

CREATE INDEX IF NOT EXISTS idx_warehouses_business_id
ON warehouses(business_id);

CREATE INDEX IF NOT EXISTS idx_stock_movements_business_date
ON stock_movements(business_id, created_at);

CREATE INDEX IF NOT EXISTS idx_invoices_business_date
ON invoices(business_id, invoice_date);

CREATE INDEX IF NOT EXISTS idx_invoices_business_status
ON invoices(business_id, status);

CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice_id
ON invoice_lines(invoice_id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_business_date
ON journal_entries(business_id, entry_date);

CREATE INDEX IF NOT EXISTS idx_journal_entry_lines_entry_id
ON journal_entry_lines(entry_id);

CREATE INDEX IF NOT EXISTS idx_accounts_business_code
ON accounts(business_id, code);

CREATE INDEX IF NOT EXISTS idx_audit_logs_business_created
ON audit_logs(business_id, created_at);

CREATE INDEX IF NOT EXISTS idx_reminders_business_due
ON reminders(business_id, due_date);

CREATE INDEX IF NOT EXISTS idx_backup_logs_business_created
ON backup_logs(business_id, created_at);
