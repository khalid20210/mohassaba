-- ════════════════════════════════════════════════════════════════════
-- 001_initial_schema.sql
-- الـ Schema المبدئي — يمثّل الجداول القائمة حالياً في النظام
-- هذا الملف لن يكسر أي بيانات موجودة (IF NOT EXISTS في كل مكان)
-- ════════════════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;

-- ── المستخدمون والصلاحيات ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    permissions TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    full_name       TEXT,
    role_id         INTEGER REFERENCES roles(id),
    business_id     INTEGER REFERENCES businesses(id),
    branch_id       INTEGER,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── المنشآت ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS businesses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    industry_type   TEXT,
    currency        TEXT    NOT NULL DEFAULT 'ر.س',
    tax_number      TEXT,
    address         TEXT,
    phone           TEXT,
    email           TEXT,
    logo_path       TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── الإعدادات ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    key         TEXT    NOT NULL,
    value       TEXT,
    UNIQUE(business_id, key)
);

-- ── تصنيفات المنتجات ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES product_categories(id),
    UNIQUE(business_id, name)
);

-- ── المنتجات ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    name            TEXT    NOT NULL,
    barcode         TEXT,
    category_id     INTEGER REFERENCES product_categories(id),
    unit            TEXT    NOT NULL DEFAULT 'قطعة',
    cost_price      REAL    NOT NULL DEFAULT 0,
    sale_price      REAL    NOT NULL DEFAULT 0,
    tax_rate        REAL    NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── المخازن ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT    NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0
);

-- ── المخزون ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    quantity     REAL    NOT NULL DEFAULT 0,
    UNIQUE(product_id, warehouse_id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    type         TEXT    NOT NULL,
    quantity     REAL    NOT NULL,
    note         TEXT,
    ref_id       INTEGER,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── جهات الاتصال (عملاء / موردون) ────────────────────────────────
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL DEFAULT 'customer',
    phone       TEXT,
    email       TEXT,
    address     TEXT,
    tax_number  TEXT,
    balance     REAL    NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── الفواتير ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    type            TEXT    NOT NULL,
    contact_id      INTEGER REFERENCES contacts(id),
    warehouse_id    INTEGER REFERENCES warehouses(id),
    subtotal        REAL    NOT NULL DEFAULT 0,
    tax_amount      REAL    NOT NULL DEFAULT 0,
    discount        REAL    NOT NULL DEFAULT 0,
    total           REAL    NOT NULL DEFAULT 0,
    payment_method  TEXT    NOT NULL DEFAULT 'cash',
    status          TEXT    NOT NULL DEFAULT 'paid',
    notes           TEXT,
    invoice_date    TEXT    NOT NULL DEFAULT (date('now')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    REAL    NOT NULL,
    unit_price  REAL    NOT NULL,
    tax_rate    REAL    NOT NULL DEFAULT 0,
    line_total  REAL    NOT NULL
);

-- ── الحسابات والقيود المحاسبية ────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    code        TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES accounts(id),
    UNIQUE(business_id, code)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    description     TEXT,
    ref_type        TEXT,
    ref_id          INTEGER,
    entry_date      TEXT    NOT NULL DEFAULT (date('now')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_entry_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id        INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    debit           REAL    NOT NULL DEFAULT 0,
    credit          REAL    NOT NULL DEFAULT 0
);

-- ── إعدادات الضرائب ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tax_settings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    tax_name    TEXT    NOT NULL DEFAULT 'ضريبة القيمة المضافة',
    rate        REAL    NOT NULL DEFAULT 15,
    is_active   INTEGER NOT NULL DEFAULT 1,
    UNIQUE(business_id)
);
