-- 003_workforce_api_foundation.sql
-- Workforce + Agents + API-first foundation

CREATE TABLE IF NOT EXISTS employees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    user_id         INTEGER,
    full_name       TEXT NOT NULL,
    phone           TEXT,
    role_label      TEXT,
    base_salary     REAL NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT,
    UNIQUE (business_id, full_name),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS shift_blind_closures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    employee_id     INTEGER NOT NULL,
    shift_date      TEXT NOT NULL,
    expected_cash   REAL NOT NULL DEFAULT 0,
    counted_cash    REAL NOT NULL DEFAULT 0,
    shortage_amount REAL NOT NULL DEFAULT 0,
    overage_amount  REAL NOT NULL DEFAULT 0,
    notes           TEXT,
    closed_by       INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (closed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS payroll_deductions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    employee_id     INTEGER NOT NULL,
    source_type     TEXT NOT NULL,
    source_id       INTEGER,
    amount          REAL NOT NULL,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at      TEXT,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id       INTEGER NOT NULL,
    full_name         TEXT NOT NULL,
    phone             TEXT,
    whatsapp_number   TEXT,
    commission_rate   REAL NOT NULL DEFAULT 0,
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_invoice_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    agent_id        INTEGER NOT NULL,
    invoice_id      INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (business_id, invoice_id),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_commissions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id       INTEGER NOT NULL,
    agent_id          INTEGER NOT NULL,
    invoice_id        INTEGER NOT NULL,
    invoice_total     REAL NOT NULL,
    commission_rate   REAL NOT NULL,
    commission_amount REAL NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at           TEXT,
    UNIQUE (business_id, invoice_id),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_employees_business ON employees (business_id);
CREATE INDEX IF NOT EXISTS idx_shift_closures_business_date ON shift_blind_closures (business_id, shift_date);
CREATE INDEX IF NOT EXISTS idx_payroll_deductions_business ON payroll_deductions (business_id, employee_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_business ON agents (business_id, is_active);
CREATE INDEX IF NOT EXISTS idx_agent_commissions_business ON agent_commissions (business_id, agent_id, status);
