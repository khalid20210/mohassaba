-- Migration 018: Medical Sector - Add missing columns & tables
-- تحديث قطاع الصحة: أعمدة ناقصة وجداول جديدة

-- ── إضافة أعمدة ناقصة لجدول patients ──────────────────────────────────────
ALTER TABLE patients ADD COLUMN file_number TEXT;
ALTER TABLE patients ADD COLUMN height REAL;
ALTER TABLE patients ADD COLUMN weight REAL;
ALTER TABLE patients ADD COLUMN chronic_diseases TEXT;
ALTER TABLE patients ADD COLUMN allergies TEXT;
ALTER TABLE patients ADD COLUMN last_visit DATE;
ALTER TABLE patients ADD COLUMN insurance_company_id INTEGER;
ALTER TABLE patients ADD COLUMN insurance_policy_number TEXT;
ALTER TABLE patients ADD COLUMN notes TEXT;

-- ── إضافة أعمدة ناقصة لجدول appointments ───────────────────────────────────
ALTER TABLE appointments ADD COLUMN appointment_type TEXT DEFAULT 'كشف';
ALTER TABLE appointments ADD COLUMN visit_fee REAL DEFAULT 0;
ALTER TABLE appointments ADD COLUMN insurance_covered REAL DEFAULT 0;
ALTER TABLE appointments ADD COLUMN paid_by_patient REAL DEFAULT 0;
ALTER TABLE appointments ADD COLUMN updated_at TEXT;

-- ── إضافة أعمدة لجدول patient_visits ───────────────────────────────────────
ALTER TABLE patient_visits ADD COLUMN vital_bp TEXT;
ALTER TABLE patient_visits ADD COLUMN vital_temp REAL;
ALTER TABLE patient_visits ADD COLUMN vital_pulse INTEGER;
ALTER TABLE patient_visits ADD COLUMN vital_weight REAL;
ALTER TABLE patient_visits ADD COLUMN follow_up_date DATE;
ALTER TABLE patient_visits ADD COLUMN created_at TEXT DEFAULT (datetime('now'));

-- ── جدول شركات التأمين ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insurance_companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name        TEXT NOT NULL,
    name_en     TEXT,
    contract_number TEXT,
    coverage_percent REAL DEFAULT 80,
    max_coverage REAL DEFAULT 0,
    contact_name TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    address     TEXT,
    is_active   INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

-- ── جدول الخدمات الطبية وقائمة الأسعار ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS medical_services (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    service_code TEXT,
    name        TEXT NOT NULL,
    category    TEXT,   -- كشف، اشعة، تحليل، عملية، علاج طبيعي، خدمات أخرى
    price       REAL DEFAULT 0,
    insurance_price REAL DEFAULT 0,
    duration_min INTEGER DEFAULT 30,
    is_active   INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

-- ── جدول الأطباء ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name        TEXT NOT NULL,
    specialty   TEXT,
    license_number TEXT,
    phone       TEXT,
    email       TEXT,
    schedule    TEXT,   -- JSON: أيام وساعات العمل
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

-- ── ترقيم الملفات الطبية ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS medical_file_counter (
    business_id INTEGER PRIMARY KEY,
    last_number INTEGER DEFAULT 0
);

-- ── شجرة حسابات المرضى/التأمين ──────────────────────────────────────────────
-- يُضاف للحسابات الموجودة في accounts table
INSERT OR IGNORE INTO accounts (business_id, code, name, account_type, parent_id, is_active, created_at)
SELECT 
    b.id,
    '1130',
    'ذمم مدينة - مرضى',
    'asset',
    NULL,
    1,
    datetime('now')
FROM businesses b
WHERE NOT EXISTS (
    SELECT 1 FROM accounts WHERE business_id = b.id AND code = '1130'
);

INSERT OR IGNORE INTO accounts (business_id, code, name, account_type, parent_id, is_active, created_at)
SELECT 
    b.id,
    '1131',
    'ذمم مدينة - شركات التأمين',
    'asset',
    NULL,
    1,
    datetime('now')
FROM businesses b
WHERE NOT EXISTS (
    SELECT 1 FROM accounts WHERE business_id = b.id AND code = '1131'
);

INSERT OR IGNORE INTO accounts (business_id, code, name, account_type, parent_id, is_active, created_at)
SELECT 
    b.id,
    '4100',
    'إيرادات الخدمات الطبية',
    'revenue',
    NULL,
    1,
    datetime('now')
FROM businesses b
WHERE NOT EXISTS (
    SELECT 1 FROM accounts WHERE business_id = b.id AND code = '4100'
);

INSERT OR IGNORE INTO accounts (business_id, code, name, account_type, parent_id, is_active, created_at)
SELECT 
    b.id,
    '4101',
    'إيرادات الصيدلية',
    'revenue',
    NULL,
    1,
    datetime('now')
FROM businesses b
WHERE NOT EXISTS (
    SELECT 1 FROM accounts WHERE business_id = b.id AND code = '4101'
);

INSERT OR IGNORE INTO accounts (business_id, code, name, account_type, parent_id, is_active, created_at)
SELECT 
    b.id,
    '4102',
    'إيرادات التأمين الطبي',
    'revenue',
    NULL,
    1,
    datetime('now')
FROM businesses b
WHERE NOT EXISTS (
    SELECT 1 FROM accounts WHERE business_id = b.id AND code = '4102'
);
