"""تطبيق migration 018 - قطاع الصحة - يتجاوز قيود SQLite 3.42"""
import sqlite3, os

def add_col_if_missing(c, table, col, col_def):
    existing = [r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()]
    if col not in existing:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_def}')
        print(f'  + {table}.{col}')
    else:
        print(f'  ~ {table}.{col} (exists)')

def apply(db_path):
    if not os.path.exists(db_path):
        print(f'SKIP (not found): {db_path}')
        return
    c = sqlite3.connect(db_path)
    print(f'\n=== {db_path} ===')

    # patients
    add_col_if_missing(c, 'patients', 'file_number',          'TEXT')
    add_col_if_missing(c, 'patients', 'height',               'REAL')
    add_col_if_missing(c, 'patients', 'weight',               'REAL')
    add_col_if_missing(c, 'patients', 'chronic_diseases',     'TEXT')
    add_col_if_missing(c, 'patients', 'allergies',            'TEXT')
    add_col_if_missing(c, 'patients', 'last_visit',           'DATE')
    add_col_if_missing(c, 'patients', 'insurance_company_id', 'INTEGER')
    add_col_if_missing(c, 'patients', 'insurance_policy_number', 'TEXT')
    add_col_if_missing(c, 'patients', 'notes',                'TEXT')

    # appointments
    add_col_if_missing(c, 'appointments', 'appointment_type',  "TEXT DEFAULT 'كشف'")
    add_col_if_missing(c, 'appointments', 'visit_fee',         'REAL DEFAULT 0')
    add_col_if_missing(c, 'appointments', 'insurance_covered', 'REAL DEFAULT 0')
    add_col_if_missing(c, 'appointments', 'paid_by_patient',   'REAL DEFAULT 0')
    add_col_if_missing(c, 'appointments', 'updated_at',        'TEXT')

    # patient_visits
    add_col_if_missing(c, 'patient_visits', 'vital_bp',      'TEXT')
    add_col_if_missing(c, 'patient_visits', 'vital_temp',    'REAL')
    add_col_if_missing(c, 'patient_visits', 'vital_pulse',   'INTEGER')
    add_col_if_missing(c, 'patient_visits', 'vital_weight',  'REAL')
    add_col_if_missing(c, 'patient_visits', 'follow_up_date','DATE')
    add_col_if_missing(c, 'patient_visits', 'created_at',    "TEXT DEFAULT (datetime('now'))")

    # جداول جديدة
    c.execute("""
    CREATE TABLE IF NOT EXISTS insurance_companies (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id      INTEGER NOT NULL,
        name             TEXT NOT NULL,
        name_en          TEXT,
        contract_number  TEXT,
        coverage_percent REAL DEFAULT 80,
        max_coverage     REAL DEFAULT 0,
        contact_name     TEXT,
        contact_phone    TEXT,
        contact_email    TEXT,
        address          TEXT,
        is_active        INTEGER DEFAULT 1,
        notes            TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (business_id) REFERENCES businesses(id)
    )""")
    print('  + insurance_companies table')

    c.execute("""
    CREATE TABLE IF NOT EXISTS medical_services (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id  INTEGER NOT NULL,
        service_code TEXT,
        name         TEXT NOT NULL,
        category     TEXT,
        price        REAL DEFAULT 0,
        insurance_price REAL DEFAULT 0,
        duration_min INTEGER DEFAULT 30,
        is_active    INTEGER DEFAULT 1,
        notes        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (business_id) REFERENCES businesses(id)
    )""")
    print('  + medical_services table')

    c.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id    INTEGER NOT NULL,
        name           TEXT NOT NULL,
        specialty      TEXT,
        license_number TEXT,
        phone          TEXT,
        email          TEXT,
        is_active      INTEGER DEFAULT 1,
        created_at     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (business_id) REFERENCES businesses(id)
    )""")
    print('  + doctors table')

    # شجرة الحسابات الطبية
    acct_cols = [r[1] for r in c.execute('PRAGMA table_info(accounts)').fetchall()]
    if 'account_type' in acct_cols:
        businesses = c.execute('SELECT id FROM businesses').fetchall()
        for (biz_id,) in businesses:
            for code, name, atype in [
                ('1130', 'ذمم مدينة - مرضى',           'asset'),
                ('1131', 'ذمم مدينة - شركات التأمين',  'asset'),
                ('4100', 'إيرادات الخدمات الطبية',       'revenue'),
                ('4101', 'إيرادات الصيدلية',             'revenue'),
                ('4102', 'إيرادات التأمين الطبي',        'revenue'),
            ]:
                exists = c.execute(
                    'SELECT 1 FROM accounts WHERE business_id=? AND code=?',
                    (biz_id, code)
                ).fetchone()
                if not exists:
                    c.execute("""
                        INSERT INTO accounts (business_id, code, name, account_type, account_nature, is_active, created_at)
                        VALUES (?,?,?,?,?,1,datetime('now'))
                    """, (biz_id, code, name, atype, 'debit' if atype=='asset' else 'credit'))
                    print(f'  + account {code} {name} for biz {biz_id}')

    c.commit()
    c.close()
    print('  ✅ Done')

apply('database/accounting_dev.db')
apply('database/accounting_prod.db')
