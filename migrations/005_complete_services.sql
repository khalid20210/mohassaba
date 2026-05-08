-- ╔═══════════════════════════════════════════════════════════════════════════╗
-- ║  005_complete_services.sql — اكتمال جميع الخدمات والمزايا              ║
-- ║  Inventory, Contacts, Barcode, Invoices, Medical, Projects, etc.        ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 1: INVENTORY & STOCK MANAGEMENT (المخزون والمستودع)            ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 1.1 الأصناف والمنتجات (Products Extended) ────────────────────────────────
CREATE TABLE IF NOT EXISTS product_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    sku                 TEXT,                           -- رمز المخزون (الكود التسلسلي)
    barcode             TEXT UNIQUE,                    -- الباركود
    current_qty         REAL NOT NULL DEFAULT 0,        -- الكمية الحالية
    min_qty             REAL NOT NULL DEFAULT 10,       -- الحد الأدنى للتنبيه
    max_qty             REAL NOT NULL DEFAULT 1000,     -- الحد الأقصى
    unit_cost           REAL NOT NULL DEFAULT 0,        -- سعر التكلفة
    unit_price          REAL NOT NULL DEFAULT 0,        -- سعر البيع
    expiry_date         DATE,                           -- تاريخ انتهاء الصلاحية (للصيدليات)
    serial_number       TEXT,                           -- رقم السيري (للأجهزة)
    location            TEXT,                           -- مكان التخزين في المستودع (رف أ1، إلخ)
    batch_number        TEXT,                           -- رقم الدفعة
    supplier_id         INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    last_stock_check    TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_product_inventory_biz ON product_inventory(business_id);
CREATE INDEX IF NOT EXISTS idx_product_inventory_barcode ON product_inventory(barcode);
CREATE INDEX IF NOT EXISTS idx_product_inventory_sku ON product_inventory(sku);

-- ── 1.2 حركات المخزون (Stock Movements) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS inventory_movements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    movement_type       TEXT NOT NULL CHECK(movement_type IN ('purchase','sale','return','adjustment','damage','transfer')),
    quantity            REAL NOT NULL,
    reference_type      TEXT,                           -- 'invoice', 'purchase_order', 'adjustment'
    reference_id        INTEGER,
    from_location       TEXT,
    to_location         TEXT,
    reason              TEXT,
    performed_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_biz ON inventory_movements(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_product ON inventory_movements(product_id);

-- ── 1.3 تنبيهات المخزون (Stock Alerts) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    alert_type          TEXT NOT NULL CHECK(alert_type IN ('low_stock','overstock','expiry_near','low_sales')),
    alert_message       TEXT NOT NULL,
    is_resolved         INTEGER NOT NULL DEFAULT 0,
    resolved_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stock_alerts_biz ON stock_alerts(business_id, is_resolved);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 2: CONTACTS & CUSTOMER MANAGEMENT (العملاء والموردين)          ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 2.1 جهات الاتصال الموسّعة (Contacts Extended) ───────────────────────────────
CREATE TABLE IF NOT EXISTS contacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_type        TEXT NOT NULL CHECK(contact_type IN ('customer','supplier','employee_contact','other')),
    name                TEXT NOT NULL,
    company_name        TEXT,
    phone               TEXT NOT NULL UNIQUE,
    email               TEXT UNIQUE,
    address             TEXT,
    city                TEXT,
    country             TEXT,
    tax_id              TEXT,                           -- الرقم الضريبي أو البطاقة
    iban                TEXT,                           -- رقم الحساب البنكي
    credit_limit        REAL DEFAULT 0,                 -- حد الائتمان للعملاء
    current_balance     REAL DEFAULT 0,                 -- الرصيد الحالي (دين/ائتمان)
    contact_person_name TEXT,
    contact_person_phone TEXT,
    category            TEXT,                           -- 'wholesale','retail','regular','vip'
    notes               TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
-- توافق مع قواعد قديمة تحتوي عمود type بدل contact_type
ALTER TABLE contacts ADD COLUMN contact_type TEXT;
UPDATE contacts
SET contact_type = CASE
    WHEN lower(COALESCE(type,'')) = 'supplier' THEN 'supplier'
    WHEN lower(COALESCE(type,'')) = 'customer' THEN 'customer'
    ELSE 'other'
END
WHERE contact_type IS NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_biz_type ON contacts(business_id, contact_type);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);

-- ── 2.2 معاملات العملاء (Customer Transactions) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS customer_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id          INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    transaction_type    TEXT NOT NULL CHECK(transaction_type IN ('sale','return','payment','credit_note')),
    reference_type      TEXT,                           -- 'invoice', 'manual'
    reference_id        INTEGER,
    amount              REAL NOT NULL,
    balance_before      REAL NOT NULL,
    balance_after       REAL NOT NULL,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_customer_txn_contact ON customer_transactions(contact_id, created_at DESC);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 3: BARCODE MANAGEMENT (إدارة الباركود)                        ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 3.1 قائمة الباركودات (Barcode Registry) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS barcodes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    barcode_value       TEXT NOT NULL UNIQUE,
    barcode_format      TEXT DEFAULT 'EAN13',           -- EAN13, CODE128, QR, etc.
    quantity_per_box    REAL DEFAULT 1,
    created_by          INTEGER REFERENCES users(id),
    print_date          TEXT,
    last_scanned_at     TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_barcodes_biz ON barcodes(business_id);
CREATE INDEX IF NOT EXISTS idx_barcodes_value ON barcodes(barcode_value);

-- ── 3.2 سجل المسح (Scan History) ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS barcode_scans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode_id          INTEGER NOT NULL REFERENCES barcodes(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id),
    action              TEXT NOT NULL CHECK(action IN ('sale','purchase','return','count')),
    quantity            REAL NOT NULL,
    user_id             INTEGER REFERENCES users(id),
    terminal_id         TEXT,                           -- معرّف الكاشير
    scanned_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_barcode_scans_product ON barcode_scans(product_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 4: ADVANCED INVOICES & BILLING (الفواتير المتقدمة)             ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 4.1 نماذج الفواتير (Invoice Templates) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS invoice_templates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    template_name       TEXT NOT NULL,
    template_type       TEXT CHECK(template_type IN ('sales','purchase','quotation','delivery_note')),
    header_text         TEXT,
    footer_text         TEXT,
    columns_config      TEXT,                           -- JSON array of column settings
    is_default          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 4.2 سجل الدفع (Payment Records) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payment_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    invoice_id          INTEGER REFERENCES invoices(id),
    contact_id          INTEGER REFERENCES contacts(id),
    payment_method      TEXT NOT NULL CHECK(payment_method IN ('cash','check','bank_transfer','card','credit','other')),
    amount              REAL NOT NULL,
    reference_number    TEXT,                           -- رقم الشيك، رقم العملية البنكية
    payment_date        TEXT NOT NULL DEFAULT (datetime('now')),
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_payment_records_invoice ON payment_records(invoice_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 5: MEDICAL SECTOR (القطاع الطبي - عيادات ومستشفيات)             ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 5.1 المرضى (Patients) ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    patient_name        TEXT NOT NULL,
    patient_phone       TEXT NOT NULL,
    date_of_birth       DATE,
    gender              TEXT CHECK(gender IN ('M','F','Other')),
    national_id         TEXT UNIQUE,
    email               TEXT UNIQUE,
    emergency_contact   TEXT,
    emergency_phone     TEXT,
    address             TEXT,
    medical_history     TEXT,                           -- JSON: allergies, chronic diseases, etc.
    insurance_provider  TEXT,
    insurance_policy    TEXT,
    blood_type          TEXT,
    contact_id          INTEGER REFERENCES contacts(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_patients_biz ON patients(business_id);
CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(patient_phone);
CREATE INDEX IF NOT EXISTS idx_patients_id ON patients(national_id);

-- ── 5.2 المواعيد الطبية (Appointments) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id           INTEGER REFERENCES users(id),                -- الطبيب
    appointment_date    TEXT NOT NULL,                  -- ISO 8601
    appointment_time    TEXT NOT NULL,                  -- HH:MM
    reason              TEXT,
    status              TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled','no_show','rescheduled')),
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments(doctor_id);

-- ── 5.3 الوصفات الطبية (Prescriptions) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prescriptions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    appointment_id      INTEGER REFERENCES appointments(id),
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id           INTEGER REFERENCES users(id),
    prescription_items  TEXT NOT NULL,                  -- JSON array: [{medication, dosage, frequency, duration}]
    notes               TEXT,
    is_printed          INTEGER NOT NULL DEFAULT 0,
    printed_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_prescriptions_patient ON prescriptions(patient_id);

-- ── 5.4 ملفات المريض (Patient Records/Visits) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS patient_visits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_date          TEXT NOT NULL DEFAULT (datetime('now')),
    doctor_id           INTEGER REFERENCES users(id),
    diagnosis           TEXT,
    treatment           TEXT,
    notes               TEXT,
    invoice_id          INTEGER REFERENCES invoices(id)
);
CREATE INDEX IF NOT EXISTS idx_patient_visits_patient ON patient_visits(patient_id, visit_date DESC);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 6: CONSTRUCTION SECTOR (قطاع المقاولات)                        ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 6.1 المشاريع (Projects) ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    project_name        TEXT NOT NULL,
    project_code        TEXT UNIQUE,
    client_id           INTEGER REFERENCES contacts(id),
    project_type        TEXT,                           -- 'residential', 'commercial', 'industrial', 'infrastructure'
    location            TEXT,
    start_date          DATE NOT NULL,
    planned_end_date    DATE NOT NULL,
    actual_end_date     DATE,
    budget_total        REAL NOT NULL,
    spent_total         REAL DEFAULT 0,
    remaining_budget    REAL,
    project_status      TEXT NOT NULL DEFAULT 'planning' CHECK(project_status IN ('planning','in_progress','on_hold','completed','cancelled')),
    progress_percentage REAL DEFAULT 0,
    manager_id          INTEGER REFERENCES users(id),
    description         TEXT,
    attachments         TEXT,                           -- JSON array of file paths
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_projects_biz ON projects(business_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(project_status);

-- ── 6.2 مستخلصات المشاريع (Project Extracts) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS project_extracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    extract_number      INTEGER NOT NULL,
    extract_date        TEXT NOT NULL DEFAULT (datetime('now')),
    total_work_value    REAL NOT NULL,
    previous_total      REAL NOT NULL DEFAULT 0,
    current_percentage  REAL NOT NULL,
    total_invoiced      REAL NOT NULL,
    amount_to_invoice   REAL NOT NULL,
    status              TEXT DEFAULT 'pending' CHECK(status IN ('pending','submitted','approved','invoiced','rejected')),
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_extracts_project ON project_extracts(project_id);

-- ── 6.3 معدات المقاولات (Equipment) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS equipment (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    equipment_name      TEXT NOT NULL,
    equipment_type      TEXT,                           -- 'machinery', 'vehicle', 'tool', 'safety'
    serial_number       TEXT UNIQUE,
    purchase_date       DATE,
    purchase_cost       REAL,
    current_location    TEXT,
    assigned_project_id INTEGER REFERENCES projects(id),
    status              TEXT DEFAULT 'available' CHECK(status IN ('available','in_use','maintenance','retired')),
    maintenance_log     TEXT,                           -- JSON array of maintenance records
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_equipment_biz ON equipment(business_id);
CREATE INDEX IF NOT EXISTS idx_equipment_project ON equipment(assigned_project_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 7: CAR RENTAL SECTOR (قطاع تأجير السيارات)                     ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 7.1 السيارات (Fleet Vehicles) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fleet_vehicles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    vehicle_name        TEXT NOT NULL,
    plate_number        TEXT NOT NULL UNIQUE,
    vin                 TEXT UNIQUE,                    -- Vehicle Identification Number
    vehicle_type        TEXT,                           -- 'sedan', 'suv', 'truck', 'van', 'luxury'
    make                TEXT,                           -- العلامة التجارية
    model               TEXT,
    year                INTEGER,
    color               TEXT,
    purchase_date       DATE,
    purchase_cost       REAL,
    mileage_current     INTEGER DEFAULT 0,
    fuel_type           TEXT,                           -- 'petrol', 'diesel', 'hybrid', 'electric'
    capacity_passengers INTEGER,
    ac_enabled          INTEGER DEFAULT 1,
    gps_enabled         INTEGER DEFAULT 1,
    insurance_policy    TEXT,
    insurance_expiry    DATE,
    registration_expiry DATE,
    status              TEXT DEFAULT 'available' CHECK(status IN ('available','rented','maintenance','retired')),
    rental_rate_daily   REAL NOT NULL,
    rental_rate_weekly  REAL,
    rental_rate_monthly REAL,
    notes               TEXT,
    photo_url           TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fleet_vehicles_biz ON fleet_vehicles(business_id);
CREATE INDEX IF NOT EXISTS idx_fleet_status ON fleet_vehicles(status);

-- ── 7.2 عقود الإيجار (Rental Contracts) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rental_contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    vehicle_id          INTEGER NOT NULL REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    renter_id           INTEGER REFERENCES contacts(id),
    rental_start_date   TEXT NOT NULL,
    rental_end_date     TEXT,
    rental_type         TEXT NOT NULL CHECK(rental_type IN ('daily','weekly','monthly','long_term')),
    daily_rate          REAL NOT NULL,
    total_days          INTEGER,
    total_amount        REAL NOT NULL,
    deposit_amount      REAL DEFAULT 0,
    deposit_returned    INTEGER DEFAULT 0,
    mileage_at_start    INTEGER,
    mileage_at_end      INTEGER,
    status              TEXT DEFAULT 'active' CHECK(status IN ('active','completed','cancelled','overdue')),
    driver_license_copy TEXT,
    passport_copy       TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rental_contracts_vehicle ON rental_contracts(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_rental_contracts_renter ON rental_contracts(renter_id);

-- ── 7.3 سجلات الصيانة (Maintenance Records) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS maintenance_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    vehicle_id          INTEGER NOT NULL REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    maintenance_type    TEXT NOT NULL CHECK(maintenance_type IN ('oil_change','tire_rotation','inspection','repair','accident')),
    description         TEXT,
    cost                REAL NOT NULL,
    service_provider    TEXT,
    service_date        TEXT NOT NULL DEFAULT (datetime('now')),
    mileage_at_service  INTEGER,
    next_service_date   TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_maintenance_vehicle ON maintenance_records(vehicle_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 8: RESTAURANT ADVANCED FEATURES (ميزات المطاعم المتقدمة)        ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 8.1 الوصفات (Recipes) ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recipes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    recipe_name         TEXT NOT NULL,
    product_id          INTEGER REFERENCES products(id),
    category            TEXT,                           -- 'appetizer', 'main', 'dessert', 'beverage', 'sauce'
    ingredients         TEXT NOT NULL,                  -- JSON array: [{product_id, quantity, unit, cost}]
    preparation_time    INTEGER,                        -- in minutes
    cooking_time        INTEGER,
    difficulty_level    TEXT CHECK(difficulty_level IN ('easy','medium','hard')),
    yield_quantity      REAL,
    yield_unit          TEXT,
    cost_per_unit       REAL,
    selling_price       REAL,
    description         TEXT,
    image_url           TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recipes_biz ON recipes(business_id);

-- ── 8.2 استخدام الوصفات في الفواتير (Recipe Usage Log) ───────────────────────
CREATE TABLE IF NOT EXISTS recipe_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id           INTEGER NOT NULL REFERENCES recipes(id),
    invoice_line_id     INTEGER,
    quantity            REAL NOT NULL,
    used_at             TEXT NOT NULL DEFAULT (datetime('now'))
);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 9: WHOLESALE SECTOR (قطاع الجملة)                             ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 9.1 الطلبات (Orders) ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    order_number        TEXT NOT NULL UNIQUE,
    customer_id         INTEGER REFERENCES contacts(id),
    order_date          TEXT NOT NULL DEFAULT (datetime('now')),
    delivery_date       DATE,
    order_status        TEXT DEFAULT 'pending' CHECK(order_status IN ('pending','confirmed','shipped','delivered','cancelled')),
    order_items         TEXT NOT NULL,                  -- JSON array: [{product_id, quantity, unit_price}]
    subtotal            REAL NOT NULL,
    tax_amount          REAL DEFAULT 0,
    shipping_cost       REAL DEFAULT 0,
    total_amount        REAL NOT NULL,
    payment_status      TEXT DEFAULT 'pending' CHECK(payment_status IN ('pending','partial','paid')),
    notes               TEXT,
    created_by          INTEGER REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_biz_date ON orders(business_id, order_date DESC);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);

-- ── 9.2 قوائم الأسعار (Pricing Lists) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pricing_lists (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    list_name           TEXT NOT NULL,
    description         TEXT,
    valid_from          DATE NOT NULL,
    valid_until         DATE,
    pricing_items       TEXT NOT NULL,                  -- JSON array: [{product_id, price, min_qty, category}]
    applicable_to       TEXT,                           -- 'all_customers', 'wholesale', 'specific_group'
    customer_group_id   INTEGER,                        -- if applicable_to == 'specific_group'
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pricing_lists_biz ON pricing_lists(business_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  SECTION 10: SERVICES SECTOR (قطاع الخدمات)                            ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- ── 10.1 أوامر العمل (Jobs/Work Orders) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    job_number          TEXT NOT NULL UNIQUE,
    client_id           INTEGER REFERENCES contacts(id),
    job_type            TEXT,                           -- 'plumbing', 'electrical', 'maintenance', 'consulting'
    description         TEXT NOT NULL,
    location            TEXT,
    scheduled_date      DATE NOT NULL,
    completion_date     DATE,
    technician_id       INTEGER REFERENCES users(id),
    priority            TEXT CHECK(priority IN ('low','medium','high','urgent')),
    job_status          TEXT DEFAULT 'pending' CHECK(job_status IN ('pending','scheduled','in_progress','completed','cancelled','on_hold')),
    estimated_cost      REAL,
    actual_cost         REAL,
    materials_used      TEXT,                           -- JSON array of materials
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_biz_date ON jobs(business_id, scheduled_date DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(job_status);

-- ── 10.2 العقود (Service Contracts) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS service_contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contract_number     TEXT NOT NULL UNIQUE,
    client_id           INTEGER REFERENCES contacts(id),
    contract_type       TEXT,                           -- 'maintenance', 'support', 'retainer'
    start_date          DATE NOT NULL,
    end_date            DATE,
    contract_value      REAL NOT NULL,
    billing_frequency   TEXT CHECK(billing_frequency IN ('monthly','quarterly','annually','as_needed')),
    service_description TEXT,
    contract_terms      TEXT,
    status              TEXT DEFAULT 'active' CHECK(status IN ('active','suspended','completed','terminated')),
    document_url        TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_service_contracts_client ON service_contracts(client_id);


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  FINAL: CLEANUP & INTEGRATION                                            ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

-- تحديث جدول products ليشمل معلومات إضافية
ALTER TABLE products ADD COLUMN category_id INTEGER;
ALTER TABLE products ADD COLUMN supplier_id INTEGER;
ALTER TABLE products ADD COLUMN expiry_date DATE;
ALTER TABLE products ADD COLUMN is_trackable INTEGER DEFAULT 1;

-- إنشاء index شاملة للأداء
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id);

-- جدول الملاحظات العامة (لأي جدول)
CREATE TABLE IF NOT EXISTS activity_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL,
    module              TEXT NOT NULL,                 -- 'inventory', 'contacts', 'patients', etc.
    action              TEXT NOT NULL,
    entity_id           INTEGER,
    changes_json        TEXT,                           -- JSON diff
    user_id             INTEGER,
    ip_address          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_activity_log_module ON activity_log(business_id, module, created_at DESC);

-- نهاية الـ Migration
-- جميع الجداول أنشئت بنجاح ✅
