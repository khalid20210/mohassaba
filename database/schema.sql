-- ============================================================
-- نظام المحاسبة والمستودع - هيكل قاعدة البيانات الكاملة
-- الإصدار: 1.0 | التاريخ: 2026-04-28
-- ============================================================

-- ============================================================
-- 1. جدول المنشآت / المستأجرين (Multi-Tenant)
-- ============================================================
CREATE TABLE IF NOT EXISTS businesses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    name_en         TEXT,
    tax_number      TEXT,
    cr_number       TEXT,                          -- السجل التجاري
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    city            TEXT,
    country         TEXT    DEFAULT 'YE',
    currency        TEXT    DEFAULT 'YER',         -- العملة الافتراضية
    fiscal_year_start TEXT  DEFAULT '01-01',       -- بداية السنة المالية
    industry_type   TEXT    DEFAULT 'retail',      -- retail|restaurant|construction|medical|education|wholesale|services|other
    logo_path       TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

-- View موحّدة: tenant_id كمرادف لـ business_id
CREATE VIEW IF NOT EXISTS tenants AS
SELECT
    id AS tenant_id, id AS business_id,
    name, name_en, tax_number, cr_number,
    industry_type, currency, country,
    fiscal_year_start, phone, email, address,
    is_active, created_at, updated_at
FROM businesses;

-- ============================================================
-- 2. جدول الأدوار / الصلاحيات
-- ============================================================
CREATE TABLE IF NOT EXISTS roles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,              -- مدير، محاسب، أمين مخزن، كاشير...
    permissions     TEXT    NOT NULL DEFAULT '{}', -- JSON: {"sales":true,"reports":false,...}
    is_system       INTEGER DEFAULT 0,             -- أدوار النظام لا تُحذف
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
-- 3. جدول المستخدمين
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    role_id         INTEGER NOT NULL REFERENCES roles(id),
    username        TEXT    NOT NULL,
    full_name       TEXT,
    email           TEXT,
    phone           TEXT,
    password_hash   TEXT    NOT NULL,
    is_active       INTEGER DEFAULT 1,
    last_login      TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(business_id, username)
);

-- ============================================================
-- 4. شجرة الحسابات (Chart of Accounts)
-- ============================================================
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    parent_id       INTEGER REFERENCES accounts(id),
    code            TEXT    NOT NULL,              -- مثال: 1100, 1110
    name            TEXT    NOT NULL,
    name_en         TEXT,
    account_type    TEXT    NOT NULL,              -- asset|liability|equity|revenue|expense
    account_nature  TEXT    NOT NULL,              -- debit|credit
    is_header       INTEGER DEFAULT 0,             -- 1 = حساب رئيسي (لا يُرصد مباشرة)
    is_active       INTEGER DEFAULT 1,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(business_id, code)
);

-- ============================================================
-- 5. دفتر اليومية - رؤوس القيود
-- ============================================================
CREATE TABLE IF NOT EXISTS journal_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    entry_number    TEXT    NOT NULL,              -- رقم القيد
    entry_date      TEXT    NOT NULL,              -- تاريخ القيد
    description     TEXT,
    reference_type  TEXT,    -- invoice|payment|purchase|adjustment|manual
    reference_id    INTEGER,
    total_debit     REAL    DEFAULT 0,
    total_credit    REAL    DEFAULT 0,
    is_posted       INTEGER DEFAULT 0,             -- 1 = مُرحَّل
    created_by      INTEGER REFERENCES users(id),
    posted_by       INTEGER REFERENCES users(id),
    posted_at       TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(business_id, entry_number)
);

-- ============================================================
-- 6. تفاصيل القيود اليومية
-- ============================================================
CREATE TABLE IF NOT EXISTS journal_entry_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id        INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    description     TEXT,
    debit           REAL    DEFAULT 0,
    credit          REAL    DEFAULT 0,
    cost_center     TEXT,
    line_order      INTEGER DEFAULT 0
);

-- ============================================================
-- 7. إعدادات الضرائب
-- ============================================================
CREATE TABLE IF NOT EXISTS tax_settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,              -- ضريبة القيمة المضافة، ضريبة مبيعات...
    rate            REAL    NOT NULL DEFAULT 0,    -- نسبة مئوية مثل 15
    applies_to      TEXT    DEFAULT 'all',         -- all|products|services
    account_id      INTEGER REFERENCES accounts(id), -- حساب الضريبة
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
-- 8. إعدادات عامة للمنشأة
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    key             TEXT    NOT NULL,
    value           TEXT,
    UNIQUE(business_id, key)
);

-- ============================================================
-- 9. تصنيفات المنتجات
-- ============================================================
CREATE TABLE IF NOT EXISTS product_categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    parent_id       INTEGER REFERENCES product_categories(id),
    name            TEXT    NOT NULL,
    name_en         TEXT,
    is_active       INTEGER DEFAULT 1
);

-- ============================================================
-- 10. جدول المنتجات (مدمج من ملفات CSV)
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    serial_number   TEXT,                          -- الرقم التسلسلي من الملف
    barcode         TEXT,
    name            TEXT    NOT NULL,
    name_en         TEXT,
    description     TEXT,
    product_type    TEXT    DEFAULT 'product',     -- product|service
    category_id     INTEGER REFERENCES product_categories(id),
    category_name   TEXT,                          -- اسم الصنف (من الملف)
    can_purchase    INTEGER DEFAULT 1,
    purchase_price  REAL    DEFAULT 0,
    can_sell        INTEGER DEFAULT 1,
    sale_price      REAL    DEFAULT 0,
    min_stock       REAL    DEFAULT 0,
    track_stock     INTEGER DEFAULT 1,
    is_pos          INTEGER DEFAULT 1,             -- منتج نقاط بيع
    is_active       INTEGER DEFAULT 1,
    notes           TEXT,
    -- حسابات المحاسبة المرتبطة
    inventory_account_id   INTEGER REFERENCES accounts(id),
    sales_account_id       INTEGER REFERENCES accounts(id),
    purchase_account_id    INTEGER REFERENCES accounts(id),
    cogs_account_id        INTEGER REFERENCES accounts(id),  -- تكلفة البضاعة المباعة
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(business_id, barcode)    -- الباركود فريد لكل منشأة
);

-- ============================================================
-- 11. المستودعات / المخازن
-- ============================================================
CREATE TABLE IF NOT EXISTS warehouses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    location        TEXT,
    is_default      INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1
);

-- ============================================================
-- 12. المخزون (رصيد كل منتج في كل مستودع)
-- ============================================================
CREATE TABLE IF NOT EXISTS stock (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id    INTEGER NOT NULL REFERENCES warehouses(id),
    quantity        REAL    DEFAULT 0,
    avg_cost        REAL    DEFAULT 0,
    last_updated    TEXT    DEFAULT (datetime('now')),
    UNIQUE(product_id, warehouse_id)
);

-- ============================================================
-- 13. حركات المخزون
-- ============================================================
CREATE TABLE IF NOT EXISTS stock_movements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    warehouse_id    INTEGER NOT NULL REFERENCES warehouses(id),
    movement_type   TEXT    NOT NULL, -- purchase|sale|transfer_in|transfer_out|adjustment|return
    quantity        REAL    NOT NULL,
    unit_cost       REAL    DEFAULT 0,
    reference_type  TEXT,
    reference_id    INTEGER,
    notes           TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
-- 14. الفواتير (مبيعات / مشتريات)
-- ============================================================
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    invoice_number  TEXT    NOT NULL,
    invoice_type    TEXT    NOT NULL,   -- sale|purchase|sale_return|purchase_return
    invoice_date    TEXT    NOT NULL,
    due_date        TEXT,
    party_id        INTEGER,            -- عميل أو مورد (جدول contacts)
    party_name      TEXT,
    warehouse_id    INTEGER REFERENCES warehouses(id),
    subtotal        REAL    DEFAULT 0,
    discount_pct    REAL    DEFAULT 0,
    discount_amount REAL    DEFAULT 0,
    tax_amount      REAL    DEFAULT 0,
    total           REAL    DEFAULT 0,
    paid_amount     REAL    DEFAULT 0,
    status          TEXT    DEFAULT 'draft', -- draft|issued|paid|partial|cancelled
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    notes           TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(business_id, invoice_number, invoice_type)
);

-- ============================================================
-- 15. تفاصيل الفواتير
-- ============================================================
CREATE TABLE IF NOT EXISTS invoice_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    product_id      INTEGER REFERENCES products(id),
    description     TEXT,
    quantity        REAL    NOT NULL DEFAULT 1,
    unit_price      REAL    NOT NULL DEFAULT 0,
    discount_pct    REAL    DEFAULT 0,
    discount_amount REAL    DEFAULT 0,
    tax_rate        REAL    DEFAULT 0,
    tax_amount      REAL    DEFAULT 0,
    total           REAL    NOT NULL DEFAULT 0,
    line_order      INTEGER DEFAULT 0
);

-- ============================================================
-- 16. جهات الاتصال (العملاء والموردين)
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_type    TEXT    NOT NULL,   -- customer|supplier|both
    name            TEXT    NOT NULL,
    name_en         TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    tax_number      TEXT,
    opening_balance REAL    DEFAULT 0,
    account_id      INTEGER REFERENCES accounts(id),
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
-- INDEXES للأداء
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_products_barcode       ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_business      ON products(business_id);
CREATE INDEX IF NOT EXISTS idx_products_biz_active    ON products(business_id, is_active);
CREATE INDEX IF NOT EXISTS idx_products_biz_pos       ON products(business_id, is_active, is_pos);
CREATE INDEX IF NOT EXISTS idx_products_biz_barcode   ON products(business_id, barcode);
CREATE INDEX IF NOT EXISTS idx_products_biz_name      ON products(business_id, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_products_category      ON products(business_id, category_name);
CREATE INDEX IF NOT EXISTS idx_stock_product          ON stock(product_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_date   ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_entries_ref    ON journal_entries(reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice  ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_prod   ON stock_movements(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_contacts_business      ON contacts(business_id, contact_type);
