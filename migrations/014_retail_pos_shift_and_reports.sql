-- Retail POS shift controls + analytics compatibility
CREATE TABLE IF NOT EXISTS pos_shifts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    opening_cash    REAL NOT NULL DEFAULT 0,
    closed_at       TEXT,
    closing_cash    REAL,
    expected_cash   REAL DEFAULT 0,
    sales_count     INTEGER DEFAULT 0,
    sales_total     REAL DEFAULT 0,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pos_shifts_biz_user_open ON pos_shifts(business_id, user_id, closed_at);
CREATE INDEX IF NOT EXISTS idx_pos_shifts_biz_opened_at ON pos_shifts(business_id, opened_at DESC);

ALTER TABLE invoices ADD COLUMN pos_shift_id INTEGER REFERENCES pos_shifts(id);
CREATE INDEX IF NOT EXISTS idx_invoices_pos_shift_id ON invoices(pos_shift_id);
